"""各機場免費航班 JSON 擷取與正規化。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from .http_client import async_client

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "airports.json"

CANCEL_KEYWORDS = ("取消", "cancel", "canceled", "cancelled")
DELAY_KEYWORDS = ("延誤", "delay", "delayed", "晚")


def load_airport_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _status_from_text(*texts: Any) -> str:
    blob = " ".join(str(t or "") for t in texts).lower()
    if any(k in blob for k in CANCEL_KEYWORDS):
        return "cancelled"
    if any(k in blob for k in DELAY_KEYWORDS):
        return "delayed"
    return "on_time"


def _first(*values: Any) -> str:
    for v in values:
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _compose_flight_no(*parts: Any) -> str:
    code = "".join(str(p).strip() for p in parts if p not in (None, ""))
    return code


def normalize_flight(airport: str, raw: dict[str, Any], direction: str) -> dict[str, Any]:
    if airport == "KHH":
        status_text = _first(raw.get("airFlyStatus"), raw.get("airFlyDelayCause"))
        return {
            "airport": airport,
            "direction": direction,
            "flightNo": _compose_flight_no(raw.get("airLineCode"), raw.get("airLineNum")),
            "airlineCode": _first(raw.get("airLineCode")),
            "airline": _first(raw.get("airLineName")),
            "destination": _first(raw.get("goalAirportName")),
            "origin": "",
            "scheduledTime": _format_time(_first(raw.get("expectTime"))),
            "estimatedTime": _format_time(_first(raw.get("realTime"))),
            "gate": _first(raw.get("airBoardingGate")),
            "status": _status_from_text(status_text),
            "statusText": status_text,
            "remark": _first(raw.get("airFlyDelayCause")),
        }

    if airport == "TPE":
        status_text = _first(raw.get("航班動態中文"), raw.get("備註"))
        direction_raw = _first(raw.get("方向"))
        airline_code = _first(raw.get("航空公司代碼"))
        flight_num = _first(raw.get("班次"))
        return {
            "airport": airport,
            "direction": "departure" if "出" in direction_raw else "arrival",
            "flightNo": _compose_flight_no(airline_code, flight_num),
            "airlineCode": airline_code,
            "airline": _first(raw.get("航空公司中文")),
            "destination": _first(raw.get("往來地點中文"), raw.get("往來地點")),
            "origin": "",
            "scheduledTime": _format_time(_first(raw.get("表訂時間"))),
            "estimatedTime": _format_time(_first(raw.get("預計時間"))),
            "gate": _first(raw.get("機門")),
            "status": _status_from_text(status_text),
            "statusText": status_text,
            "remark": _first(raw.get("備註")),
        }

    # TSA / RMQ 共用欄位
    status_text = _first(raw.get("AirFlyStatus"), raw.get("AirFlyDelayCause"))
    airline_code = _first(raw.get("AirLineIATA"), raw.get("AirLineCode"))
    return {
        "airport": airport,
        "direction": direction,
        "flightNo": _compose_flight_no(airline_code, raw.get("AirLineNum")),
        "airlineCode": airline_code,
        "airline": _first(raw.get("AirLineName")),
        "destination": _first(raw.get("GoalAirportName")),
        "origin": _first(raw.get("UpAirportName")),
        "scheduledTime": _format_time(
            _first(raw.get("ExpectDepartureTime"), raw.get("ExpectArrivalTime"))
        ),
        "estimatedTime": _format_time(
            _first(raw.get("RealDepartureTime"), raw.get("RealArrivalTime"))
        ),
        "gate": _first(raw.get("AirBoardingGate")),
        "status": _status_from_text(status_text),
        "statusText": status_text,
        "remark": _first(raw.get("AirFlyDelayCause")),
    }


def _format_time(value: str) -> str:
    if not value:
        return ""
    # 2026-07-06T02:00:00+08:00 -> 02:00
    if "T" in value:
        part = value.split("T", 1)[1]
        return part[:5] if len(part) >= 5 else part
    return value[:5] if len(value) >= 5 else value


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("InstantSchedule"), list):
            return payload["InstantSchedule"]
        if isinstance(payload.get("records"), list):
            return payload["records"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
    return []


async def _fetch_json(url: str) -> Any:
    async with async_client() as client:
        res = await client.get(url, headers={"Accept": "application/json"})
        res.raise_for_status()
        text = res.text.strip()
        if text.startswith("[") or text.startswith("{"):
            return json.loads(text)
        # 桃園 ODP 可能回傳 JSON Lines
        rows: list[Any] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows


async def fetch_airport_flights(code: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    flights: list[dict[str, Any]] = []

    async def add_from(url: str | None, direction: str) -> None:
        if not url:
            return
        payload = await _fetch_json(url)
        for row in _extract_rows(payload):
            flights.append(normalize_flight(code, row, direction))

    if code == "TPE":
        payload = await _fetch_json(config["departure"])
        for row in _extract_rows(payload):
            flights.append(normalize_flight(code, row, "unknown"))
        return flights

    if code == "TSA":
        await add_from(config.get("departure"), "departure")
        await add_from(config.get("arrival"), "arrival")
        return flights

    if code == "KHH":
        await add_from(config.get("departure"), "departure")
        await add_from(config.get("arrival"), "arrival")
        return flights

    if code == "RMQ":
        await add_from(config.get("departureInternational"), "departure")
        await add_from(config.get("arrivalInternational"), "arrival")
        await add_from(config.get("departureDomestic"), "departure")
        await add_from(config.get("arrivalDomestic"), "arrival")
        return flights

    return flights


async def fetch_all_flights() -> dict[str, Any]:
    config = load_airport_config()
    result: dict[str, Any] = {"airports": [], "flights": []}
    for code, airport in config.items():
        if code.startswith("_") or not isinstance(airport, dict):
            continue
        try:
            rows = await fetch_airport_flights(code, airport)
            result["airports"].append({"code": code, "name": airport.get("name", code)})
            result["flights"].extend(rows)
        except Exception as exc:  # noqa: BLE001 — 單一機場失敗不影響其他
            result["airports"].append(
                {
                    "code": code,
                    "name": airport.get("name", code),
                    "error": str(exc),
                }
            )
    return result


def filter_flights(
    flights: list[dict[str, Any]],
    airline_code: str = "",
    flight_number: str = "",
) -> list[dict[str, Any]]:
    """依航空公司代碼 + 班次篩選（如 5J + 310 → 5J310）。"""
    airline = airline_code.strip().upper()
    number = flight_number.strip()
    if not airline and not number:
        return flights

    matched: list[dict[str, Any]] = []
    for f in flights:
        fno = (f.get("flightNo") or "").upper().replace(" ", "")
        ac = (f.get("airlineCode") or "").upper()

        if airline and number:
            target = f"{airline}{number}"
            if fno == target or (fno.startswith(airline) and fno.endswith(number)):
                matched.append(f)
                continue
        if airline and not number:
            if ac == airline or fno.startswith(airline):
                matched.append(f)
                continue
        if number and not airline:
            if fno.endswith(number) or f" {number}" in f" {fno}":
                matched.append(f)

    return matched


async def search_flights(airline_code: str = "", flight_number: str = "") -> dict[str, Any]:
    data = await fetch_all_flights()
    hits = filter_flights(data["flights"], airline_code, flight_number)
    return {
        "airports": data["airports"],
        "flights": hits,
        "query": {"airlineCode": airline_code.strip(), "flightNumber": flight_number.strip()},
        "count": len(hits),
    }
