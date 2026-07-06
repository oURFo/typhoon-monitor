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

# 葵花 8 號全圓盤可見光（JMA 公開圖）
SATELLITE_IMAGE_URL = (
    "https://www.data.jma.go.jp/mscweb/data/himawari/img/fullgif/latest/Hs_latest.jpg"
)


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


def satellite_meta() -> dict[str, str]:
    return {
        "url": SATELLITE_IMAGE_URL,
        "bounds": "95,105,0,45",
        "attribution": "JMA Himawari",
    }
