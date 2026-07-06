"""除錯 CWA 原始回應結構（不輸出授權碼）。"""

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
        res = await client.get(CWA_TYPHOON_URL, params=params)
        data = res.json()

    out = ROOT / "scripts" / "cwa_debug.json"
  # 只保留結構摘要
    summary = {
        "status_code": res.status_code,
        "success": data.get("success"),
        "message": data.get("message"),
        "records_keys": list((data.get("records") or {}).keys()),
    }
    records = data.get("records") or {}
    tc = records.get("TropicalCyclones") or records.get("tropicalCyclones")
    summary["tropicalCyclones_type"] = type(tc).__name__
    if isinstance(tc, dict):
        summary["tropicalCyclones_keys"] = list(tc.keys())
        raw = tc.get("TropicalCyclone") or tc.get("tropicalCyclone")
        summary["tropicalCyclone_type"] = type(raw).__name__
        if isinstance(raw, dict):
            summary["tropicalCyclone_sample_keys"] = list(raw.keys())[:20]
        elif isinstance(raw, list):
            summary["tropicalCyclone_count"] = len(raw)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
