"""抓取各機場航班並寫入 data/flights.json（供 GitHub Actions 排程使用）。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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


async def main() -> int:
    stale = load_stale_by_airport()
    data = await fetch_all_flights(stale_by_airport=stale)
    prepared = prepare_snapshot(data.get("flights", []))
    flights = prepared["flights"]
    total = len(flights)
    if total == 0:
        print("ERROR: no flights fetched", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "updatedAt": now,
        "airports": data.get("airports", []),
        "flights": flights,
        "byAirport": prepared["byAirport"],
        "byAirportDirection": prepared["byAirportDirection"],
        "byDirection": prepared["byDirection"],
        "count": total,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {total} flights -> {OUTPUT}")

    tpe_rows = [f for f in flights if f.get("airport") == "TPE"]
    tpe_meta = next((a for a in payload["airports"] if a.get("code") == "TPE"), {})
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
                    "count": len(tpe_rows),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"  TPE snapshot -> {TPE_OUTPUT} ({len(tpe_rows)} rows)")
    elif tpe_meta.get("stale"):
        print(f"  TPE: kept stale cache ({len(tpe_rows)} rows)")

    for airport in payload["airports"]:
        code = airport.get("code", "?")
        err = airport.get("error")
        n = sum(1 for f in flights if f.get("airport") == code)
        if err:
            print(f"  {code}: {n} rows ({err})")
        else:
            print(f"  {code}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
