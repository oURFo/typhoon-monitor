"""交通部 TDX 航空 FIDS（桃園機場 fallback）。"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http_client import async_client

TDX_TOKEN_URL = (
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
)
TDX_FIDS_TPE_URL = (
    "https://tdx.transportdata.tw/api/basic/v2/Air/FIDS/Airport/TPE?$format=JSON"
)
TDX_AIRPORT_URL = (
    "https://tdx.transportdata.tw/api/basic/v2/Air/Airport"
    "?$format=JSON&$top=5000"
)

ROOT = Path(__file__).resolve().parent.parent
AIRPORT_IATA_CACHE_PATH = ROOT / "data" / "airport-iata-zh.json"
AIRPORT_IATA_CACHE_TTL_SEC = 7 * 24 * 3600

_token_cache: dict[str, Any] = {}
_airport_iata_memory: dict[str, str] | None = None


def tdx_configured() -> bool:
    return bool(os.getenv("TDX_CLIENT_ID", "").strip() and os.getenv("TDX_CLIENT_SECRET", "").strip())


def tdx_zh_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("Zh_tw") or value.get("En") or "").strip()
    return str(value or "").strip()


def airport_zh_label(code: str, names: dict[str, str]) -> str:
    key = (code or "").strip().upper()
    if not key:
        return ""
    return names.get(key, key)


AIRPORT_IATA_OVERRIDES: dict[str, str] = {
    "CJJ": "清州",
    "HND": "東京",
    "NRT": "東京",
    "ICN": "首爾",
    "GMP": "首爾",
}


def build_airport_iata_map(rows: list[Any]) -> dict[str, str]:
    mapping: dict[str, str] = dict(AIRPORT_IATA_OVERRIDES)
    for row in rows:
        if not isinstance(row, dict):
            continue
        iata = str(row.get("AirportIATA") or row.get("AirportID") or "").strip().upper()
        if not iata:
            continue
        city = tdx_zh_name(row.get("AirportCityName"))
        name = tdx_zh_name(row.get("AirportName"))
        label = city or name
        if label:
            mapping[iata] = label
    return mapping


def _load_airport_iata_cache() -> dict[str, str] | None:
    if not AIRPORT_IATA_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(AIRPORT_IATA_CACHE_PATH.read_text(encoding="utf-8"))
        updated_at = payload.get("updatedAt")
        if not updated_at:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(str(updated_at))
        if age.total_seconds() > AIRPORT_IATA_CACHE_TTL_SEC:
            return None
        names = payload.get("names")
        if isinstance(names, dict) and names:
            return {str(k).upper(): str(v) for k, v in names.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return None


def _save_airport_iata_cache(names: dict[str, str]) -> None:
    AIRPORT_IATA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(names),
        "names": names,
    }
    AIRPORT_IATA_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def get_airport_iata_zh_map() -> dict[str, str]:
    global _airport_iata_memory  # noqa: PLW0603
    if _airport_iata_memory:
        return _airport_iata_memory

    cached = _load_airport_iata_cache()
    if cached:
        _airport_iata_memory = cached
        return cached

    token = await get_tdx_token()
    async with async_client(timeout=60.0) as client:
        res = await client.get(
            TDX_AIRPORT_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        res.raise_for_status()
        data = res.json()

    rows: list[Any] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("Airports") or data.get("Airport") or []
        if isinstance(rows, dict):
            rows = [rows]

    mapping = build_airport_iata_map(rows)
    if not mapping:
        raise ValueError("TDX 機場對照表為空")

    _save_airport_iata_cache(mapping)
    _airport_iata_memory = mapping
    return mapping


async def get_tdx_token() -> str:
    client_id = os.getenv("TDX_CLIENT_ID", "").strip()
    client_secret = os.getenv("TDX_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("未設定 TDX_CLIENT_ID / TDX_CLIENT_SECRET")

    now = time.monotonic()
    if _token_cache.get("token") and now < float(_token_cache.get("expires_at", 0)):
        return str(_token_cache["token"])

    async with async_client(timeout=30.0) as client:
        res = await client.post(
            TDX_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        res.raise_for_status()
        data = res.json()

    token = data["access_token"]
    expires_in = int(data.get("expires_in", 3600))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(expires_in - 120, 60)
    return token


async def fetch_tpe_fids_payload() -> dict[str, Any]:
    token = await get_tdx_token()
    async with async_client(timeout=60.0) as client:
        res = await client.get(
            TDX_FIDS_TPE_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
        res.raise_for_status()
        data = res.json()

    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    raise ValueError("TDX FIDS 回應格式無法解析")
