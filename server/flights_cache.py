"""航班資料快取（Render 等雲端環境避免每次請求逾時）。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

CACHE_TTL_SEC = 300
_list_cache: dict[str, Any] | None = None
_list_cache_at: float = 0.0
_airport_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_warm_lock = asyncio.Lock()
_warming = False


def _is_fresh(ts: float) -> bool:
    return (time.time() - ts) < CACHE_TTL_SEC


def get_cached_list() -> dict[str, Any] | None:
    if _list_cache and _is_fresh(_list_cache_at):
        return _list_cache
    return None


def get_cached_airport(code: str) -> dict[str, Any] | None:
    entry = _airport_cache.get(code.upper())
    if entry and _is_fresh(entry[0]):
        return entry[1]
    return None


def set_list_cache(data: dict[str, Any]) -> None:
    global _list_cache, _list_cache_at
    _list_cache = data
    _list_cache_at = time.time()


def set_airport_cache(code: str, data: dict[str, Any]) -> None:
    _airport_cache[code.upper()] = (time.time(), data)


async def warm_cache(fetch_all) -> None:
    """背景預熱完整航班快取。"""
    global _warming
    async with _warm_lock:
        if _warming or get_cached_list():
            return
        _warming = True
    try:
        data = await fetch_all()
        set_list_cache(data)
    finally:
        _warming = False
