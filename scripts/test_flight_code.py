import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.flights import fetch_airport_flights, load_airport_config


async def main() -> None:
    rows = await fetch_airport_flights("TPE", load_airport_config()["TPE"])
    hits = [f for f in rows if f["flightNo"].endswith("310")]
    print("samples", [f["flightNo"] for f in hits[:3]])


asyncio.run(main())
