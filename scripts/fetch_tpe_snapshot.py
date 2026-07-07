"""桃園機場航班快照（獨立排程，較長 timeout／重試）。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.flights import fetch_tpe_flights_with_fallback, merge_tpe_snapshot, prepare_snapshot  # noqa: E402
from server.tdx import AIRPORT_IATA_CACHE_PATH, tdx_configured  # noqa: E402

OUTPUT = ROOT / "data" / "flights.json"
TPE_OUTPUT = ROOT / "data" / "tpe-flights.json"
PUBLIC_IATA = ROOT / "public" / "data" / "airport-iata-zh.json"


def load_prev_tpe_meta() -> dict[str, Any]:
    if not TPE_OUTPUT.exists():
        return {}
    try:
        data = json.loads(TPE_OUTPUT.read_text(encoding="utf-8"))
        return (data.get("cacheMeta") or {}).get("TPE") or {}
    except json.JSONDecodeError:
        return {}


def build_tpe_cache_meta(
    *,
    prev: dict[str, Any],
    now_iso: str,
    row_count: int,
    error: str | None,
    data_source: str = "",
) -> dict[str, Any]:
    if error:
        cached_at = prev.get("cachedAt") or prev.get("lastSuccessAt")
        return {
            "cachedAt": cached_at,
            "lastAttemptAt": now_iso,
            "lastSuccessAt": prev.get("lastSuccessAt") or cached_at,
            "failCount": int(prev.get("failCount") or 0) + 1,
            "lastError": error,
            "stale": True,
            "rowCount": row_count,
            "dataSource": prev.get("dataSource"),
        }
    return {
        "cachedAt": now_iso,
        "lastAttemptAt": now_iso,
        "lastSuccessAt": now_iso,
        "failCount": 0,
        "lastError": None,
        "stale": False,
        "rowCount": row_count,
        "dataSource": data_source or "odp",
    }


def merge_into_flights_json(tpe_payload: dict[str, Any], tpe_meta: dict[str, Any]) -> None:
    if not OUTPUT.exists():
        return
    try:
        base = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    merged = merge_tpe_snapshot(base, tpe_payload)
    merged["updatedAt"] = datetime.now(timezone.utc).isoformat()
    cache_meta = {**(merged.get("cacheMeta") or {}), "TPE": tpe_meta}
    merged["cacheMeta"] = cache_meta
    airports = [a for a in merged.get("airports", []) if a.get("code") != "TPE"]
    airports.append({"code": "TPE", "name": "桃園國際機場", **tpe_meta})
    merged["airports"] = airports
    OUTPUT.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  merged TPE into {OUTPUT}")


async def main() -> int:
    prev_meta = load_prev_tpe_meta()
    now = datetime.now(timezone.utc).isoformat()

    print(
        f"TPE fetch settings: timeout={os.getenv('TPE_TIMEOUT', '120')}s "
        f"connect={os.getenv('TPE_CONNECT_TIMEOUT', '90')}s "
        f"retries={os.getenv('TPE_FETCH_RETRIES', '3')} "
        f"tdx={'yes' if tdx_configured() else 'no'}"
    )

    rows, err, source = await fetch_tpe_flights_with_fallback()

    if err or not rows:
        msg = err or "桃園航班資料為空"
        print(f"ERROR: TPE fetch failed: {msg}", file=sys.stderr)
        if not tdx_configured():
            print("  hint: set TDX_CLIENT_ID and TDX_CLIENT_SECRET for cloud fallback", file=sys.stderr)
        if TPE_OUTPUT.exists() and prev_meta:
            print(f"  kept existing {TPE_OUTPUT}")
        return 1

    prepared = prepare_snapshot(rows)
    tpe_meta = build_tpe_cache_meta(
        prev=prev_meta,
        now_iso=now,
        row_count=len(rows),
        error=None,
        data_source=source,
    )
    tpe_payload = {
        "updatedAt": now,
        "flights": prepared["flights"],
        "byAirport": prepared["byAirport"],
        "byAirportDirection": prepared["byAirportDirection"],
        "byDirection": prepared["byDirection"],
        "cacheMeta": {"TPE": tpe_meta},
        "count": len(rows),
    }
    TPE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TPE_OUTPUT.write_text(json.dumps(tpe_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} TPE flights -> {TPE_OUTPUT} (source={source})")

    if AIRPORT_IATA_CACHE_PATH.exists():
        PUBLIC_IATA.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(AIRPORT_IATA_CACHE_PATH, PUBLIC_IATA)
        print(f"  synced {PUBLIC_IATA}")

    merge_into_flights_json(tpe_payload, tpe_meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
