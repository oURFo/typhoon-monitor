"""合併桃園快照進主 flights.json（主排程不直接抓桃園）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.flights import merge_tpe_snapshot

TPE_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "tpe-flights.json"


def load_tpe_snapshot() -> dict[str, Any] | None:
    if not TPE_OUTPUT.exists():
        return None
    try:
        return json.loads(TPE_OUTPUT.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def attach_tpe_to_payload(payload: dict[str, Any], tpe_data: dict[str, Any]) -> dict[str, Any]:
    merged = merge_tpe_snapshot(payload, tpe_data)
    tpe_meta = (tpe_data.get("cacheMeta") or {}).get("TPE") or {}
    cache_meta = {**(merged.get("cacheMeta") or {}), "TPE": tpe_meta}
    merged["cacheMeta"] = cache_meta
    airports = [a for a in merged.get("airports", []) if a.get("code") != "TPE"]
    airports.append({"code": "TPE", "name": "桃園國際機場", **tpe_meta})
    merged["airports"] = airports
    return merged
