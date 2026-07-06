"""共用 HTTP 客戶端（部分政府站台在 Windows Python 3.14 有 SSL 驗證問題）。"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 30.0


def _build_timeout(value: object) -> httpx.Timeout:
    if isinstance(value, httpx.Timeout):
        return value
    read = float(value) if value is not None else DEFAULT_TIMEOUT
    return httpx.Timeout(connect=min(60.0, read), read=read, write=30.0, pool=30.0)


def async_client(**kwargs: object) -> httpx.AsyncClient:
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
    opts = {"timeout": _build_timeout(timeout), "follow_redirects": True, "verify": False}
    opts.update(kwargs)
    return httpx.AsyncClient(**opts)
