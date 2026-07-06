import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import cwa, flights


async def main() -> None:
    typhoons = await cwa.fetch_typhoons()
    print("typhoons", len(typhoons), typhoons[0]["nameEn"] if typhoons else "none")
    if not typhoons:
        print("(若為 0，可能目前 CWA 無活躍熱帶氣旋資料)")
    data = await flights.fetch_all_flights()
    print("flights", len(data["flights"]))
    for a in data["airports"]:
        print(" ", a["code"], a.get("error", "ok"))


if __name__ == "__main__":
    asyncio.run(main())
