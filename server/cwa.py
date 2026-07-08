"""CWA 颱風資料擷取與正規化。"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from pathlib import Path

from .http_client import async_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CWA_TYPHOON_URL = (
    "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-005"
)
CWA_WARN_URL = (
    "https://opendata.cwa.gov.tw/api/v1/rest/datastore/W-C0034-001"
)
CWA_SATELLITE_FILEAPI = (
    "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/O-B0032-001"
)

# JMA 葵花備援（與 CWA 颱風座標系不完全一致，僅作 fallback）
SATELLITE_AREA = "se2"
JMA_SATELLITE_BOUNDS = [[0, 105], [30, 140]]
SATELLITE_BASE = "https://www.data.jma.go.jp/mscweb/data/himawari/img"


def _get_key() -> str:
    key = os.getenv("CWA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未設定 CWA_API_KEY")
    return key


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_point(raw: dict[str, Any]) -> dict[str, Any]:
    lon = float(raw.get("CoordinateLongitude", 0))
    lat = float(raw.get("CoordinateLatitude", 0))
    point: dict[str, Any] = {
        "time": raw.get("DateTime") or raw.get("InitialTime"),
        "lon": lon,
        "lat": lat,
        "windSpeed": _to_int(raw.get("MaxWindSpeed")),
        "gustSpeed": _to_int(raw.get("MaxGustSpeed")),
        "pressure": _to_int(raw.get("Pressure")),
        "movingSpeed": _to_int(raw.get("MovingSpeed")),
        "movingDirection": raw.get("MovingDirection"),
        "forecastHour": raw.get("ForecastHour"),
    }
    for key, label in (("Circle15ms", "radius7"), ("Circle25ms", "radius10")):
        circle = raw.get(key)
        if isinstance(circle, dict) and circle.get("Radius"):
            point[label] = _to_int(circle.get("Radius"))
    prob = raw.get("Radius70PercentProbability")
    if prob:
        point["probabilityRadius"] = _to_int(prob)
    return point


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def normalize_typhoon(raw: dict[str, Any]) -> dict[str, Any]:
    analysis = raw.get("AnalysisData") or raw.get("analysisData") or {}
    track = [_parse_point(p) for p in _as_list(analysis.get("Fix"))]

    forecast_block = raw.get("ForecastData") or raw.get("forecastData") or {}
    forecasts: list[dict[str, Any]] = []
    for p in _as_list(forecast_block.get("Fix")):
        item = _parse_point(p)
        item["initialTime"] = p.get("InitialTime")
        forecasts.append(item)

    # 若分析路徑為空，以預報起點作為目前位置
    latest = track[-1] if track else (forecasts[0] if forecasts else {})

    return {
        "id": f"{raw.get('Year')}-{raw.get('CwaTyNo') or raw.get('CwaTdNo')}",
        "year": raw.get("Year"),
        "nameEn": raw.get("TyphoonName"),
        "nameZh": raw.get("CwaTyphoonName"),
        "typhoonNo": raw.get("CwaTyNo"),
        "tdNo": raw.get("CwaTdNo"),
        "track": track,
        "forecast": forecasts,
        "current": latest,
        "updatedAt": latest.get("time") if latest else None,
    }


def _extract_cyclones(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("records") or {}
    block = records.get("TropicalCyclones") or records.get("tropicalCyclones") or {}
    if not isinstance(block, dict):
        return []
    raw = block.get("TropicalCyclone") or block.get("tropicalCyclone")
    return [c for c in _as_list(raw) if isinstance(c, dict)]


async def fetch_typhoons() -> list[dict[str, Any]]:
    params = {"Authorization": _get_key()}
    async with async_client() as client:
        res = await client.get(CWA_TYPHOON_URL, params=params)
        res.raise_for_status()
        data = res.json()
    if data.get("success") == "false":
        raise RuntimeError(data.get("message", "CWA 颱風 API 錯誤"))
    cyclones = _extract_cyclones(data)
    return [normalize_typhoon(c) for c in cyclones]


async def fetch_typhoon_warnings() -> list[dict[str, Any]]:
    params = {"Authorization": _get_key()}
    async with async_client() as client:
        res = await client.get(CWA_WARN_URL, params=params)
        res.raise_for_status()
        data = res.json()
    locations = data.get("records", {}).get("location", [])
    warnings: list[dict[str, Any]] = []
    for loc in _as_list(locations):
        warnings.append(
            {
                "name": loc.get("locationName"),
                "typhoonName": loc.get("typhoonName"),
                "issueTime": loc.get("issueTime"),
                "weather": loc.get("weather"),
            }
        )
    return warnings


def _parse_range_pair(value: str) -> tuple[float, float]:
    lo, hi = str(value).split("-", 1)
    return float(lo), float(hi)


def _bounds_from_cwa_geo(geo: dict[str, Any]) -> list[list[float]]:
    lon_lo, lon_hi = _parse_range_pair(geo["LongitudeRange"])
    lat_lo, lat_hi = _parse_range_pair(geo["LatitudeRange"])
    return [[lat_lo, lon_lo], [lat_hi, lon_hi]]


def _extract_cwa_satellite_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    root = data.get("cwaopendata") or data
    dataset = root.get("dataset")
    if not isinstance(dataset, dict):
        return None
    geo = dataset.get("GeoInfo") or {}
    resource = dataset.get("Resource") or {}
    obs = dataset.get("ObsTime") or {}
    url = str(resource.get("ProductURL") or "").strip()
    if not url or "LongitudeRange" not in geo or "LatitudeRange" not in geo:
        return None
    return {
        "url": url,
        "bounds": _bounds_from_cwa_geo(geo),
        "attribution": "CWA Himawari",
        "region": "East Asia",
        "source": "cwa",
        "observedAt": obs.get("Datetime"),
        "description": resource.get("ResourceDesc"),
    }


async def fetch_cwa_satellite_meta() -> dict[str, Any] | None:
    """CWA 高解析東亞衛星圖（與颱風路徑同一座標基準）。"""
    params = {"Authorization": _get_key(), "format": "JSON"}
    async with async_client(timeout=20.0) as client:
        res = await client.get(CWA_SATELLITE_FILEAPI, params=params, follow_redirects=True)
        res.raise_for_status()
        payload = _extract_cwa_satellite_payload(res.json())
    if not payload:
        return None
    async with async_client(timeout=15.0) as client:
        head = await client.head(
            payload["url"],
            headers={"User-Agent": "TyphoonMonitor/1.0"},
            follow_redirects=True,
        )
        if head.status_code >= 400:
            return None
    return payload


def _himawari_slot(offset_slots: int = 0) -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc) - timedelta(minutes=10 * offset_slots)
    minute = (now.minute // 10) * 10
    slot = now.replace(minute=minute, second=0, microsecond=0)
    return slot.strftime("%H%M")


def _himawari_url(offset_slots: int = 0, *, area: str = SATELLITE_AREA) -> str:
    slot = _himawari_slot(offset_slots)
    if area == "fd_":
        return f"{SATELLITE_BASE}/fd_/fd__vir_{slot}.jpg"
    return f"{SATELLITE_BASE}/{area}/{area}_vir_{slot}.jpg"


async def _resolve_jma_satellite_meta() -> dict[str, Any]:
    headers = {"User-Agent": "TyphoonMonitor/1.0"}
    async with async_client(timeout=15.0) as client:
        for offset in range(6):
            url = _himawari_url(offset)
            try:
                res = await client.head(url, headers=headers)
                if res.status_code == 200:
                    return {
                        "url": url,
                        "bounds": JMA_SATELLITE_BOUNDS,
                        "attribution": "JMA Himawari",
                        "region": "Southeast Asia 2",
                        "source": "jma",
                        "slot": _himawari_slot(offset),
                    }
            except Exception:  # noqa: BLE001
                continue
    return {
        "url": _himawari_url(1),
        "bounds": JMA_SATELLITE_BOUNDS,
        "attribution": "JMA Himawari",
        "region": "Southeast Asia 2",
        "source": "jma",
        "slot": _himawari_slot(1),
        "error": "衛星圖暫時無法取得",
    }


async def resolve_satellite_meta() -> dict[str, Any]:
    """優先使用 CWA 東亞衛星圖（與颱風座標一致），失敗則改 JMA。"""
    try:
        cwa = await fetch_cwa_satellite_meta()
        if cwa:
            return cwa
    except Exception as exc:  # noqa: BLE001
        fallback = await _resolve_jma_satellite_meta()
        fallback["error"] = f"CWA 衛星圖失敗，改用 JMA：{exc}"
        return fallback
    return await _resolve_jma_satellite_meta()


def satellite_meta() -> dict[str, Any]:
    """同步 fallback（未驗證 URL）。"""
    return {
        "url": _himawari_url(1),
        "bounds": JMA_SATELLITE_BOUNDS,
        "attribution": "JMA Himawari",
        "source": "jma",
        "slot": _himawari_slot(1),
    }
