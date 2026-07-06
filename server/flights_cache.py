"""已改由 GitHub Actions 更新 data/flights.json；此模組保留供相容。"""

from __future__ import annotations

from typing import Any

REFRESH_INTERVAL_SEC = 600


def is_refreshing() -> bool:
    return False


def get_last_error() -> str | None:
    return None


def get_snapshot(*, allow_stale: bool = True) -> dict[str, Any] | None:
    return None
