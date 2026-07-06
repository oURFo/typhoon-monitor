"""共用 HTTP 客戶端（部分政府站台在 Windows Python 3.14 有 SSL 驗證問題）。"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 30.0


def async_client(**kwargs: object) -> httpx.AsyncClient:
    opts = {"timeout": DEFAULT_TIMEOUT, "follow_redirects": True, "verify": False}
    opts.update(kwargs)
    return httpx.AsyncClient(**opts)
