"""交通部 TDX 航空 FIDS（桃園機場 fallback）。"""

from __future__ import annotations

import os
import time
from typing import Any

from .http_client import async_client

TDX_TOKEN_URL = (
    "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
)
TDX_FIDS_TPE_URL = (
    "https://tdx.transportdata.tw/api/basic/v2/Air/FIDS/Airport/TPE?$format=JSON"
)

_token_cache: dict[str, Any] = {}


def tdx_configured() -> bool:
    return bool(os.getenv("TDX_CLIENT_ID", "").strip() and os.getenv("TDX_CLIENT_SECRET", "").strip())


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
