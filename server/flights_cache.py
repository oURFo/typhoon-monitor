"""航班資料快取：背景每 10 分鐘更新，API 只讀快取。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

REFRESH_INTERVAL_SEC = 600
_snapshot: dict[str, Any] | None = None
_snapshot_at: float = 0.0
_refresh_lock = asyncio.Lock()
_refreshing = False
_last_error: str | None = None
_scheduler_task: asyncio.Task | None = None


def is_refreshing() -> bool:
    return _refreshing


def get_last_error() -> str | None:
    return _last_error


def get_snapshot(*, allow_stale: bool = True) -> dict[str, Any] | None:
    if _snapshot is None:
        return None
    if allow_stale:
        return _snapshot
    age = time.time() - _snapshot_at
    if age < REFRESH_INTERVAL_SEC:
        return _snapshot
    return None


def set_snapshot(data: dict[str, Any]) -> None:
    global _snapshot, _snapshot_at, _last_error
    _snapshot = {
        **data,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "cacheReady": True,
    }
    _snapshot_at = time.time()
    _last_error = None


def snapshot_age_sec() -> float | None:
    if _snapshot is None:
        return None
    return time.time() - _snapshot_at


async def run_refresh(fetch_fn: Callable[[], Awaitable[dict[str, Any]]]) -> bool:
    """執行一次完整更新；失敗時保留舊快取。"""
    global _refreshing, _last_error
    async with _refresh_lock:
        if _refreshing:
            return False
        _refreshing = True
        try:
            data = await fetch_fn()
            set_snapshot(data)
            return True
        except Exception as exc:  # noqa: BLE001
            _last_error = str(exc).strip() or type(exc).__name__
            return False
        finally:
            _refreshing = False


async def _refresh_loop(fetch_fn: Callable[[], Awaitable[dict[str, Any]]]) -> None:
    while True:
        await run_refresh(fetch_fn)
        await asyncio.sleep(REFRESH_INTERVAL_SEC)


def start_scheduler(fetch_fn: Callable[[], Awaitable[dict[str, Any]]]) -> asyncio.Task:
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        return _scheduler_task
    _scheduler_task = asyncio.create_task(_refresh_loop(fetch_fn))
    return _scheduler_task
