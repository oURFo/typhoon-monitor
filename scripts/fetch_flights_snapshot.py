"""抓取各機場航班並寫入 data/flights.json（供 GitHub Actions 排程使用）。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.flights import _flights_by_airport, fetch_all_flights, prepare_snapshot  # noqa: E402

OUTPUT = ROOT / "data" / "flights.json"
TPE_OUTPUT = ROOT / "data" / "tpe-flights.json"


def load_stale_by_airport() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}

    if TPE_OUTPUT.exists():
        try:
            tpe_data = json.loads(TPE_OUTPUT.read_text(encoding="utf-8"))
            tpe_rows = tpe_data.get("byAirport", {}).get("TPE") or tpe_data.get("flights", [])
            if tpe_rows:
                grouped["TPE"] = tpe_rows
        except json.JSONDecodeError:
            pass

    if OUTPUT.exists():
        try:
            data = json.loads(OUTPUT.read_text(encoding="utf-8"))
            for code, rows in _flights_by_airport(data.get("flights", [])).items():
                if rows and code not in grouped:
                    grouped[code] = rows
        except json.JSONDecodeError:
            pass

    return grouped


def load_prev_cache_meta() -> dict[str, dict[str, Any]]:
    prev: dict[str, dict[str, Any]] = {}
    if OUTPUT.exists():
        try:
            data = json.loads(OUTPUT.read_text(encoding="utf-8"))
            prev.update(data.get("cacheMeta") or {})
        except json.JSONDecodeError:
            pass
    if TPE_OUTPUT.exists():
        try:
            tpe = json.loads(TPE_OUTPUT.read_text(encoding="utf-8"))
            tpe_meta = (tpe.get("cacheMeta") or {}).get("TPE")
            if not tpe_meta and tpe.get("updatedAt"):
                tpe_meta = {
                    "cachedAt": tpe.get("updatedAt"),
                    "lastSuccessAt": tpe.get("updatedAt"),
                    "failCount": 0,
                }
            if tpe_meta:
                prev["TPE"] = {**prev.get("TPE", {}), **tpe_meta}
        except json.JSONDecodeError:
            pass
    return prev


def build_cache_meta(
    airports_meta: list[dict[str, Any]],
    row_counts: dict[str, int],
    prev_meta: dict[str, dict[str, Any]],
    now_iso: str,
) -> dict[str, dict[str, Any]]:
    cache_meta: dict[str, dict[str, Any]] = {}
    for airport in airports_meta:
        code = airport["code"]
        prev = prev_meta.get(code, {})
        stale = bool(airport.get("stale"))
        err = airport.get("error")
        rows = row_counts.get(code, 0)

        if stale:
            cached_at = prev.get("cachedAt") or prev.get("lastSuccessAt")
            entry = {
                "cachedAt": cached_at,
                "lastAttemptAt": now_iso,
                "lastSuccessAt": prev.get("lastSuccessAt") or cached_at,
                "failCount": int(prev.get("failCount") or 0) + 1,
                "lastError": err,
                "stale": True,
                "rowCount": rows,
            }
        elif err:
            entry = {
                "cachedAt": prev.get("cachedAt"),
                "lastAttemptAt": now_iso,
                "lastSuccessAt": prev.get("lastSuccessAt"),
                "failCount": int(prev.get("failCount") or 0) + 1,
                "lastError": err,
                "stale": False,
                "rowCount": 0,
            }
        else:
            entry = {
                "cachedAt": now_iso,
                "lastAttemptAt": now_iso,
                "lastSuccessAt": now_iso,
                "failCount": 0,
                "lastError": None,
                "stale": False,
                "rowCount": rows,
            }

        cache_meta[code] = entry
        airport.update(entry)
    return cache_meta


async def main() -> int:
    stale = load_stale_by_airport()
    prev_meta = load_prev_cache_meta()
    data = await fetch_all_flights(stale_by_airport=stale)
    prepared = prepare_snapshot(data.get("flights", []))
    flights = prepared["flights"]
    total = len(flights)
    if total == 0:
        print("ERROR: no flights fetched", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    row_counts = {code: len(rows) for code, rows in prepared["byAirport"].items()}
    airports_meta = data.get("airports", [])
    cache_meta = build_cache_meta(airports_meta, row_counts, prev_meta, now)

    payload = {
        "updatedAt": now,
        "airports": airports_meta,
        "flights": flights,
        "byAirport": prepared["byAirport"],
        "byAirportDirection": prepared["byAirportDirection"],
        "byDirection": prepared["byDirection"],
        "cacheMeta": cache_meta,
        "count": total,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {total} flights -> {OUTPUT}")

    tpe_rows = [f for f in flights if f.get("airport") == "TPE"]
    tpe_meta = cache_meta.get("TPE", {})
    if tpe_rows and not tpe_meta.get("stale"):
        tpe_prepared = prepare_snapshot(tpe_rows)
        TPE_OUTPUT.write_text(
            json.dumps(
                {
                    "updatedAt": now,
                    "flights": tpe_prepared["flights"],
                    "byAirport": tpe_prepared["byAirport"],
                    "byAirportDirection": tpe_prepared["byAirportDirection"],
                    "byDirection": tpe_prepared["byDirection"],
                    "cacheMeta": {"TPE": tpe_meta},
                    "count": len(tpe_rows),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  TPE snapshot -> {TPE_OUTPUT} ({len(tpe_rows)} rows)")
    elif tpe_meta.get("stale"):
        print(
            f"  TPE: kept stale cache ({len(tpe_rows)} rows, "
            f"failCount={tpe_meta.get('failCount')}, cachedAt={tpe_meta.get('cachedAt')})"
        )

    for airport in airports_meta:
        code = airport.get("code", "?")
        cm = cache_meta.get(code, {})
        err = cm.get("lastError")
        n = cm.get("rowCount", 0)
        if cm.get("stale"):
            print(f"  {code}: {n} rows (stale, fail={cm.get('failCount')}, cached={cm.get('cachedAt')})")
        elif err:
            print(f"  {code}: {n} rows ({err})")
        else:
            print(f"  {code}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
