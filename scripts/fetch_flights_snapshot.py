"""抓取各機場航班並寫入 data/flights.json（供 GitHub Actions 排程使用）。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.flights import fetch_all_flights  # noqa: E402

OUTPUT = ROOT / "data" / "flights.json"


async def main() -> int:
    data = await fetch_all_flights(use_stale_fallback=False)
    total = len(data.get("flights", []))
    if total == 0:
        print("ERROR: no flights fetched", file=sys.stderr)
        return 1

    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "airports": data.get("airports", []),
        "flights": data.get("flights", []),
        "count": total,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {total} flights -> {OUTPUT}")
    for airport in payload["airports"]:
        code = airport.get("code", "?")
        err = airport.get("error")
        if err:
            print(f"  {code}: ERROR {err}")
        else:
            n = sum(1 for f in payload["flights"] if f.get("airport") == code)
            print(f"  {code}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
