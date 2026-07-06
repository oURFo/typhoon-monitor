import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from server.flights import _fetch_json, load_airport_config


async def main() -> None:
    cfg = load_airport_config()["TPE"]
    data = await _fetch_json(cfg["departure"])
    rows = data if isinstance(data, list) else [data]
    for row in rows[:3]:
        if isinstance(row, dict):
            keys = {k: row.get(k) for k in row if "航" in k or "班" in k or "公司" in k}
            print(json.dumps(keys, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
