"""各機場免費航班 JSON 擷取與正規化。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .http_client import async_client

TAIWAN_TZ = timezone(timedelta(hours=8))

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "airports.json"

FETCH_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TyphoonMonitor/1.0 (educational; +https://github.com/oURFo/typhoon-monitor)",
}

AIRPORT_TIMEOUT = 45.0
TPE_TIMEOUT = 120.0
TPE_FETCH_RETRIES = 3
# 桃園資料量大，放最後抓；其他機場先完成以確保快取有內容
AIRPORT_FETCH_ORDER = ("TSA", "KHH", "RMQ", "TPE")

CANCEL_KEYWORDS = ("取消", "cancel", "canceled", "cancelled")
DELAY_KEYWORDS = ("延誤", "delay", "delayed", "晚")
DEPARTED_KEYWORDS = ("離站", "departed", "已飛", "已出發")
ARRIVED_KEYWORDS = ("已抵", "arrived", "已到", "抵達機坪", "抵達")
PAST_GRACE_MIN = 20
OVERDUE_MIN = 15


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


def _tpe_direction(raw: str) -> str:
    code = raw.strip().upper()
    if code == "D" or "出" in raw:
        return "departure"
    if code == "A" or "抵" in raw:
        return "arrival"
    return "unknown"


def _normalize_tca_style(airport: str, raw: dict[str, Any], direction: str) -> dict[str, Any]:
    """高雄、臺中機場（小寫 camelCase JSON）。"""
    status_text = _first(raw.get("airFlyStatus"), raw.get("airFlyDelayCause"))
    airline_code = _first(raw.get("airLineCode"), raw.get("airLineIATA"))
    scheduled = _first(
        raw.get("expectTime"),
        raw.get("expectDepartureTime"),
        raw.get("expectArrivalTime"),
    )
    estimated = _first(
        raw.get("realTime"),
        raw.get("realDepartureTime"),
        raw.get("realArrivalTime"),
    )
    return {
        "airport": airport,
        "direction": direction,
        "flightNo": _compose_flight_no(airline_code, raw.get("airLineNum")),
        "airlineCode": airline_code,
        "airline": _first(raw.get("airLineName")),
        "destination": _first(raw.get("goalAirportName")),
        "origin": _first(raw.get("upAirportName")),
        "scheduledTime": _format_time(scheduled),
        "estimatedTime": _format_time(estimated),
        "gate": _first(raw.get("airBoardingGate")),
        "status": _status_from_text(status_text),
        "statusText": status_text,
        "remark": _first(raw.get("airFlyDelayCause")),
    }


def normalize_flight(airport: str, raw: dict[str, Any], direction: str) -> dict[str, Any]:
    if airport in ("KHH", "RMQ"):
        return _normalize_tca_style(airport, raw, direction)

    if airport == "TPE":
        status_text = _first(raw.get("航班動態中文"), raw.get("備註"))
        direction_raw = _first(raw.get("方向"))
        airline_code = _first(raw.get("航空公司代碼"))
        flight_num = _first(raw.get("班次"))
        return {
            "airport": airport,
            "direction": _tpe_direction(direction_raw),
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

    # 松山機場（PascalCase JSON）
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
    if "T" in value:
        part = value.split("T", 1)[1]
        return part[:5] if len(part) >= 5 else part
    if len(value) >= 5 and value[2] == ":":
        return value[:5]
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) >= 4:
        return f"{digits[:2]}:{digits[2:4]}"
    return value[:5] if len(value) >= 5 else value


def _parse_time_minutes(value: str) -> int | None:
    if not value:
        return None
    raw = str(value).strip()
    if ":" in raw:
        parts = raw.split(":", 1)
        try:
            h, m = int(parts[0]), int(parts[1][:2])
            if 0 <= h < 24 and 0 <= m < 60:
                return h * 60 + m
        except ValueError:
            pass
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 4:
        h, m = int(digits[:2]), int(digits[2:4])
        if 0 <= h < 24 and 0 <= m < 60:
            return h * 60 + m
    return None


def _taiwan_now_minutes() -> int:
    now = datetime.now(TAIWAN_TZ)
    return now.hour * 60 + now.minute


def _times_differ(scheduled: str, estimated: str) -> bool:
    sm = _parse_time_minutes(scheduled)
    em = _parse_time_minutes(estimated)
    if sm is not None and em is not None:
        return sm != em
    return bool(scheduled and estimated and scheduled != estimated)


def _is_past_flight(flight: dict[str, Any], now_mins: int) -> bool:
    blob = f"{flight.get('statusText', '')} {flight.get('remark', '')}".lower()
    direction = flight.get("direction")
    if direction == "arrival":
        if any(k in blob for k in ARRIVED_KEYWORDS):
            return True
    elif any(k in blob for k in DEPARTED_KEYWORDS):
        return True

    ref = _parse_time_minutes(flight.get("estimatedTime") or "") or _parse_time_minutes(
        flight.get("scheduledTime") or ""
    )
    if ref is None:
        return False
    return ref < now_mins - PAST_GRACE_MIN


def enrich_flight(flight: dict[str, Any], now_mins: int) -> dict[str, Any]:
    """推斷顯示狀態、變更時間、是否已飛，供快照預處理。"""
    out = dict(flight)
    sched = out.get("scheduledTime") or ""
    est = out.get("estimatedTime") or ""
    sched_m = _parse_time_minutes(sched)
    est_m = _parse_time_minutes(est)
    sort_m = sched_m if sched_m is not None else (est_m if est_m is not None else 9999)

    blob = f"{out.get('statusText', '')} {out.get('remark', '')}".lower()
    is_past = _is_past_flight(out, now_mins)
    time_changed = _times_differ(sched, est)
    overdue = sched_m is not None and not is_past and now_mins > sched_m + OVERDUE_MIN

    if any(k in blob for k in CANCEL_KEYWORDS):
        status = "cancelled"
    elif time_changed and not is_past:
        status = "changed"
    elif (any(k in blob for k in DELAY_KEYWORDS) or overdue) and not is_past:
        status = "delayed"
    else:
        status = "on_time"

    if status == "changed":
        display_time = est or sched
    elif status == "delayed":
        display_time = est if time_changed else ""
    else:
        display_time = est or sched

    out["sortMinutes"] = sort_m
    out["isPast"] = is_past
    out["status"] = status
    out["displayTime"] = display_time
    return out


def sort_flight_list(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(flights, key=lambda f: (1 if f.get("isPast") else 0, f.get("sortMinutes", 9999)))


def prepare_snapshot(flights: list[dict[str, Any]]) -> dict[str, Any]:
    """豐富化並依機場預排序（供前端直接讀取，避免即時排序卡頓）。"""
    now_mins = _taiwan_now_minutes()
    enriched = [enrich_flight(f, now_mins) for f in flights]
    grouped = _flights_by_airport(enriched)
    sorted_by = {code: sort_flight_list(rows) for code, rows in grouped.items()}

    all_sorted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code in AIRPORT_FETCH_ORDER:
        if code in sorted_by:
            all_sorted.extend(sorted_by[code])
            seen.add(code)
    for code, rows in sorted_by.items():
        if code not in seen:
            all_sorted.extend(rows)

    return {"flights": all_sorted, "byAirport": sorted_by}


def _parse_json_text(text: str) -> Any:
    text = text.strip()
    if text.startswith("[") or text.startswith("{"):
        return json.loads(text)
    rows: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


async def _fetch_json(url: str, *, timeout: float = AIRPORT_TIMEOUT) -> Any:
    async with async_client(timeout=timeout) as client:
        res = await client.get(url, headers=FETCH_HEADERS)
        res.raise_for_status()
        text = res.content.decode("utf-8")
        return _parse_json_text(text)


async def _fetch_tpe_csv(url: str) -> list[dict[str, Any]]:
    async with async_client(timeout=TPE_TIMEOUT) as client:
        res = await client.get(url, headers=FETCH_HEADERS)
        res.raise_for_status()
        text = res.content.decode("utf-8-sig")
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]


async def _fetch_tpe_rows(url: str) -> list[dict[str, Any]]:
    last_exc: Exception | None = None
    for attempt in range(TPE_FETCH_RETRIES):
        try:
            if "format=csv" in url:
                return await _fetch_tpe_csv(url)
            payload = await _fetch_json(url, timeout=TPE_TIMEOUT)
            rows = _extract_rows(payload)
            if rows:
                return rows
            raise ValueError("桃園航班資料為空")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 < TPE_FETCH_RETRIES:
                await asyncio.sleep(2 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


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


async def fetch_airport_flights(code: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    flights: list[dict[str, Any]] = []

    async def add_from(url: str | None, direction: str) -> None:
        if not url:
            return
        payload = await _fetch_json(url)
        for row in _extract_rows(payload):
            flights.append(normalize_flight(code, row, direction))

    if code == "TPE":
        rows = await _fetch_tpe_rows(config["departure"])
        return [normalize_flight(code, row, "unknown") for row in rows]

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


async def _fetch_airport_bundle(code: str, airport: dict[str, Any]) -> dict[str, Any]:
    name = airport.get("name", code)
    try:
        rows = await fetch_airport_flights(code, airport)
        return {
            "code": code,
            "name": name,
            "flights": rows,
            "count": len(rows),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).strip() or type(exc).__name__
        return {
            "code": code,
            "name": name,
            "flights": [],
            "count": 0,
            "error": msg,
        }


def _flights_by_airport(flights: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in flights:
        code = row.get("airport", "")
        grouped.setdefault(code, []).append(row)
    return grouped


async def fetch_all_flights(
    *,
    stale_by_airport: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """依序抓取各機場；失敗時可沿用 stale_by_airport 的舊資料。"""
    config = load_airport_config()
    prev_by_airport = stale_by_airport or {}

    airport_map = {
        code: airport
        for code, airport in config.items()
        if not code.startswith("_") and isinstance(airport, dict)
    }

    all_flights: list[dict[str, Any]] = []
    airports_meta: list[dict[str, Any]] = []

    for code in AIRPORT_FETCH_ORDER:
        airport = airport_map.get(code)
        if not airport:
            continue
        bundle = await _fetch_airport_bundle(code, airport)
        meta: dict[str, Any] = {"code": code, "name": bundle["name"]}

        if bundle["error"] and code in prev_by_airport and prev_by_airport[code]:
            rows = prev_by_airport[code]
            meta["stale"] = True
            meta["error"] = f"{bundle['error']}（顯示快取）"
        elif bundle["error"]:
            meta["error"] = bundle["error"]
            rows = []
        else:
            rows = bundle["flights"]

        airports_meta.append(meta)
        all_flights.extend(rows)

    return {"airports": airports_meta, "flights": all_flights}


async def fetch_airport(code: str) -> dict[str, Any]:
    config = load_airport_config()
    airport = config.get(code.upper())
    if not airport or not isinstance(airport, dict):
        raise ValueError(f"未知機場代碼: {code}")
    bundle = await _fetch_airport_bundle(code.upper(), airport)
    return {
        "airport": bundle["code"],
        "name": bundle["name"],
        "flights": bundle["flights"],
        "count": bundle["count"],
        "error": bundle["error"],
    }


def filter_flights(
    flights: list[dict[str, Any]],
    airline_code: str = "",
    flight_number: str = "",
    destination: str = "",
) -> list[dict[str, Any]]:
    """依目的地、航空公司代碼、班次篩選。"""
    rows = flights
    dest_q = destination.strip().lower()
    if dest_q:
        rows = [
            f
            for f in rows
            if dest_q in (f.get("destination") or "").lower()
            or dest_q in (f.get("origin") or "").lower()
        ]

    airline = airline_code.strip().upper()
    number = flight_number.strip()
    if not airline and not number:
        return rows

    matched: list[dict[str, Any]] = []
    for f in rows:
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


SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "flights.json"


def load_flights_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {"airports": [], "flights": [], "updatedAt": None, "count": 0}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
