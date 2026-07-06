"""檢查颱風物件內層欄位名稱。"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from server.cwa import CWA_TYPHOON_URL, _get_key
from server.http_client import async_client


async def main() -> None:
    params = {"Authorization": _get_key()}
    async with async_client() as client:
        data = (await client.get(CWA_TYPHOON_URL, params=params)).json()

    records = data.get("records") or {}
    block = records.get("TropicalCyclones") or records.get("tropicalCyclones") or {}
    raw = block.get("TropicalCyclone") or block.get("tropicalCyclone")
    if isinstance(raw, list):
        raw = raw[0]
    print("top_keys", list(raw.keys()))
    analysis = raw.get("AnalysisData") or raw.get("analysisData") or {}
    print("analysis_keys", list(analysis.keys()) if isinstance(analysis, dict) else analysis)
    forecast = raw.get("ForecastData") or raw.get("forecastData") or {}
    print("forecast_type", type(forecast).__name__)
    if isinstance(forecast, dict):
        print("forecast_keys", list(forecast.keys()))
        fixes = forecast.get("Fix")
        if isinstance(fixes, list) and fixes:
            print("forecast_fix_sample", list(fixes[0].keys()))


if __name__ == "__main__":
    asyncio.run(main())
