"""各機場免費航班 JSON 擷取與正規化。"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .http_client import async_client
from .tdx import airport_zh_label, fetch_tpe_fids_payload, get_airport_iata_zh_map, tdx_configured

TAIWAN_TZ = timezone(timedelta(hours=8))

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "airports.json"

FETCH_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TyphoonMonitor/1.0 (educational; +https://github.com/oURFo/typhoon-monitor)",
}

AIRPORT_TIMEOUT = 45.0
TPE_TIMEOUT = float(os.getenv("TPE_TIMEOUT", "120"))
TPE_CONNECT_TIMEOUT = float(os.getenv("TPE_CONNECT_TIMEOUT", "90"))
TPE_FETCH_RETRIES = int(os.getenv("TPE_FETCH_RETRIES", "3"))
# 桃園資料量大，放最後抓；其他機場先完成以確保快取有內容
AIRPORT_FETCH_ORDER = ("TSA", "KHH", "RMQ", "TPE")

CANCEL_KEYWORDS = ("取消", "cancel", "canceled", "cancelled")
DELAY_KEYWORDS = ("延誤", "delay", "delayed", "晚")
DEPARTED_KEYWORDS = ("離站", "departed", "已飛", "已出發", "出發departed")
ARRIVED_KEYWORDS = ("已抵", "arrived", "已到", "抵達機坪", "抵達")
PAST_GRACE_MIN = 20
OVERDUE_MIN = 15
FLIGHT_LOOKAHEAD_DAYS = 1  # 今天 + 明天

# TDX FIDS 僅有 IATA 代碼，常用航司中文對照
AIRLINE_ZH: dict[str, str] = {
    "AE": "華信",
    "B7": "立榮",
    "BR": "長榮",
    "CI": "華航",
    "CX": "國泰",
    "DL": "達美",
    "EK": "阿聯酋",
    "EY": "阿提哈德",
    "FM": "上海航空",
    "GE": "復興",
    "GK": "捷星日本",
    "HO": "吉祥",
    "IT": "台灣虎航",
    "JL": "日航",
    "JX": "星宇",
    "KE": "大韓",
    "MH": "馬航",
    "MM": "樂桃",
    "NH": "全日空",
    "OZ": "韓亞",
    "PR": "菲航",
    "QR": "卡達",
    "SQ": "新航",
    "TG": "泰航",
    "TR": "酷航",
    "UA": "聯合",
    "VN": "越航",
    "Z2": "亞航",
}


def _airline_zh(code: str) -> str:
    c = (code or "").strip().upper()
    return AIRLINE_ZH.get(c, c)


def _parse_flight_date(*values: Any) -> str:
    """回傳台灣日期 YYYY-MM-DD；無法解析則空字串。"""
    for value in values:
        raw = _first(value)
        if not raw:
            continue
        text = raw.replace("Z", "+00:00")
        try:
            if "T" in text:
                dt = datetime.fromisoformat(text)
            else:
                dt = datetime.strptime(text[:10], "%Y-%m-%d")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TAIWAN_TZ)
            return dt.astimezone(TAIWAN_TZ).date().isoformat()
        except ValueError:
            continue
    return ""


def _allowed_flight_dates(extra_days: int = FLIGHT_LOOKAHEAD_DAYS) -> set[str]:
    today = datetime.now(TAIWAN_TZ).date()
    return {(today + timedelta(days=i)).isoformat() for i in range(extra_days + 1)}


def _keep_flight_by_date(flight: dict[str, Any], allowed: set[str]) -> bool:
    flight_date = _first(flight.get("flightDate"))
    if not flight_date:
        return True  # ODP 等無日期來源，交由後續狀態／去重處理
    return flight_date in allowed


def _flight_identity_key(flight: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _first(flight.get("airport")),
        _first(flight.get("direction")),
        _first(flight.get("flightNo")).upper(),
        _first(flight.get("flightDate")) or _first(flight.get("scheduledTime")),
    )


def _flight_freshness_score(flight: dict[str, Any]) -> tuple[int, int, int, int]:
    """分數越高越優先保留（同一班多筆時）。"""
    blob = f"{flight.get('statusText', '')} {flight.get('remark', '')}".lower()
    has_actual = 1 if any(k in blob for k in (*DEPARTED_KEYWORDS, *ARRIVED_KEYWORDS)) else 0
    has_gate = 1 if _first(flight.get("gate")) else 0
    has_aircraft = 1 if _first(flight.get("aircraftType")) not in ("", "-") else 0
    has_est = 1 if _first(flight.get("estimatedTime")) else 0
    return (has_actual, has_gate, has_aircraft, has_est)


def dedupe_flights(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同機場／方向／班號／日期只留最新一筆；無日期時合併相近表定時間的重複列。"""
    best: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str, str]] = []
    for flight in flights:
        key = _flight_identity_key(flight)
        prev = best.get(key)
        if prev is None:
            best[key] = flight
            order.append(key)
            continue
        if _flight_freshness_score(flight) >= _flight_freshness_score(prev):
            best[key] = flight

    dated = [best[k] for k in order if _first(best[k].get("flightDate"))]
    undated = [best[k] for k in order if not _first(best[k].get("flightDate"))]
    if not undated:
        return dated

    # 無日期：同班號若表定時間相差 ≤60 分，視為同一班去重
    merged_undated: list[dict[str, Any]] = []
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for flight in undated:
        key = (
            _first(flight.get("airport")),
            _first(flight.get("direction")),
            _first(flight.get("flightNo")).upper(),
        )
        buckets.setdefault(key, []).append(flight)

    for rows in buckets.values():
        rows = sorted(rows, key=lambda f: _parse_time_minutes(f.get("scheduledTime") or "") or 9999)
        kept: list[dict[str, Any]] = []
        for flight in rows:
            mins = _parse_time_minutes(flight.get("scheduledTime") or "")
            merged = False
            for idx, existing in enumerate(kept):
                existing_mins = _parse_time_minutes(existing.get("scheduledTime") or "")
                if mins is not None and existing_mins is not None and abs(mins - existing_mins) <= 60:
                    if _flight_freshness_score(flight) >= _flight_freshness_score(existing):
                        kept[idx] = flight
                    merged = True
                    break
            if not merged:
                kept.append(flight)
        merged_undated.extend(kept)

    return dated + merged_undated


def filter_recent_flights(flights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只保留今天與明天；無日期欄位者保留後再去重。"""
    allowed = _allowed_flight_dates()
    kept = [f for f in flights if _keep_flight_by_date(f, allowed)]
    return dedupe_flights(kept)


def _normalize_tpe_tdx(
    raw: dict[str, Any],
    direction: str,
    airport_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    names = airport_names or {}
    airline_code = _first(raw.get("AirlineID"))
    if direction == "departure":
        sched = _first(raw.get("ScheduleDepartureTime"))
        est = _first(raw.get("EstimatedDepartureTime"), raw.get("ActualDepartureTime"))
        status_text = _first(raw.get("DepartureRemark"), raw.get("DepartureRemarkEn"))
        destination = airport_zh_label(_first(raw.get("ArrivalAirportID")), names)
        origin = ""
    else:
        sched = _first(raw.get("ScheduleArrivalTime"))
        est = _first(raw.get("EstimatedArrivalTime"), raw.get("ActualArrivalTime"))
        status_text = _first(raw.get("ArrivalRemark"), raw.get("ArrivalRemarkEn"))
        origin = airport_zh_label(_first(raw.get("DepartureAirportID")), names)
        destination = ""
    flight_date = _parse_flight_date(raw.get("FlightDate"), sched, est)
    return {
        "airport": "TPE",
        "direction": direction,
        "flightNo": _compose_flight_no(airline_code, raw.get("FlightNumber")),
        "airlineCode": airline_code,
        "airline": _airline_zh(airline_code),
        "destination": destination,
        "origin": origin,
        "scheduledTime": _format_time(sched),
        "estimatedTime": _format_time(est),
        "flightDate": flight_date,
        "terminal": _first(raw.get("Terminal")),
        "gate": _first(raw.get("Gate")),
        "aircraftType": _first(raw.get("AcType")),
        "status": _status_from_text(status_text),
        "statusText": status_text,
        "remark": "",
    }


async def fetch_tpe_from_tdx() -> list[dict[str, Any]]:
    payload = await fetch_tpe_fids_payload()
    airport_names = await get_airport_iata_zh_map()
    flights: list[dict[str, Any]] = []
    for row in payload.get("FIDSDeparture") or []:
        if isinstance(row, dict):
            flights.append(_normalize_tpe_tdx(row, "departure", airport_names))
    for row in payload.get("FIDSArrival") or []:
        if isinstance(row, dict):
            flights.append(_normalize_tpe_tdx(row, "arrival", airport_names))
    return filter_recent_flights(flights)


def _tpe_skip_odp() -> bool:
    return os.getenv("TPE_SKIP_ODP", "").strip().lower() in {"1", "true", "yes"}


async def fetch_tpe_flights_with_fallback() -> tuple[list[dict[str, Any]], str | None, str]:
    """桃園：先 ODP CSV，失敗則 TDX FIDS。回傳 (flights, error, source)。"""
    config = load_airport_config()["TPE"]
    odp_err = ""
    if not _tpe_skip_odp():
        try:
            rows = await _fetch_tpe_rows(config["departure"])
            if rows:
                flights = [normalize_flight("TPE", row, "unknown") for row in rows]
                return flights, None, "odp"
            odp_err = "桃園 ODP 資料為空"
        except Exception as exc:  # noqa: BLE001
            odp_err = str(exc).strip() or type(exc).__name__

    if not tdx_configured():
        return [], odp_err or "桃園抓取失敗", ""

    try:
        flights = await fetch_tpe_from_tdx()
        if flights:
            return flights, None, "tdx"
        tdx_empty = "TDX 資料為空"
        return [], f"ODP: {odp_err}; {tdx_empty}" if odp_err else tdx_empty, ""
    except Exception as exc:  # noqa: BLE001
        tdx_err = str(exc).strip() or type(exc).__name__
        combined = f"ODP: {odp_err}; TDX: {tdx_err}" if odp_err else tdx_err
        return [], combined, ""


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
        "terminal": "",
        "gate": _first(raw.get("airBoardingGate")),
        "aircraftType": _first(raw.get("airPlaneType")),
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
        flight_date = _parse_flight_date(
            raw.get("航班日期"),
            raw.get("日期"),
            raw.get("表訂時間"),
            raw.get("預計時間"),
        )
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
            "flightDate": flight_date,
            "terminal": _first(raw.get("航廈")),
            "gate": _first(raw.get("機門")),
            "aircraftType": _first(raw.get("機型")),
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
        "terminal": "",
        "gate": _first(raw.get("AirBoardingGate")),
        "aircraftType": _first(raw.get("AirPlaneType")),
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
    flight_date = _first(flight.get("flightDate"))
    today = datetime.now(TAIWAN_TZ).date().isoformat()
    if flight_date:
        if flight_date > today:
            return False
        if flight_date < today:
            return True

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
    today = datetime.now(TAIWAN_TZ).date().isoformat()
    return sorted(
        flights,
        key=lambda f: (
            0 if (_first(f.get("flightDate")) or today) == today else 1,
            1 if f.get("isPast") else 0,
            f.get("sortMinutes", 9999),
            _first(f.get("flightDate")),
        ),
    )


def prepare_snapshot(flights: list[dict[str, Any]]) -> dict[str, Any]:
    """豐富化並依機場＋起飛/抵達預排序（供前端直接讀取）。"""
    now_mins = _taiwan_now_minutes()
    filtered = filter_recent_flights(flights)
    enriched = [enrich_flight(f, now_mins) for f in filtered]
    grouped = _flights_by_airport(enriched)

    by_airport: dict[str, list[dict[str, Any]]] = {}
    by_airport_direction: dict[str, dict[str, list[dict[str, Any]]]] = {}
    by_direction: dict[str, list[dict[str, Any]]] = {"departure": [], "arrival": []}

    for code, rows in grouped.items():
        deps = [f for f in rows if f.get("direction") == "departure"]
        arrs = [f for f in rows if f.get("direction") == "arrival"]
        dep_sorted = sort_flight_list(deps)
        arr_sorted = sort_flight_list(arrs)
        by_airport_direction[code] = {"departure": dep_sorted, "arrival": arr_sorted}
        by_airport[code] = dep_sorted + arr_sorted
        by_direction["departure"].extend(dep_sorted)
        by_direction["arrival"].extend(arr_sorted)

    by_direction["departure"] = sort_flight_list(by_direction["departure"])
    by_direction["arrival"] = sort_flight_list(by_direction["arrival"])

    all_sorted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for code in AIRPORT_FETCH_ORDER:
        if code in by_airport:
            all_sorted.extend(by_airport[code])
            seen.add(code)
    for code, rows in by_airport.items():
        if code not in seen:
            all_sorted.extend(rows)

    return {
        "flights": all_sorted,
        "byAirport": by_airport,
        "byAirportDirection": by_airport_direction,
        "byDirection": by_direction,
    }


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
    import httpx

    timeout = httpx.Timeout(
        connect=TPE_CONNECT_TIMEOUT,
        read=TPE_TIMEOUT,
        write=30.0,
        pool=30.0,
    )
    async with async_client(timeout=timeout) as client:
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
        flights, err, _source = await fetch_tpe_flights_with_fallback()
        if err:
            raise RuntimeError(err)
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
    skip_airports: set[str] | None = None,
) -> dict[str, Any]:
    """依序抓取各機場；失敗時可沿用 stale_by_airport 的舊資料。"""
    config = load_airport_config()
    prev_by_airport = stale_by_airport or {}
    skip = {code.upper() for code in (skip_airports or set())}

    airport_map = {
        code: airport
        for code, airport in config.items()
        if not code.startswith("_") and isinstance(airport, dict)
    }

    all_flights: list[dict[str, Any]] = []
    airports_meta: list[dict[str, Any]] = []

    for code in AIRPORT_FETCH_ORDER:
        if code in skip:
            continue
        airport = airport_map.get(code)
        if not airport:
            continue
        bundle = await _fetch_airport_bundle(code, airport)
        meta: dict[str, Any] = {"code": code, "name": bundle["name"]}

        if bundle["error"] and code in prev_by_airport and prev_by_airport[code]:
            rows = prev_by_airport[code]
            meta["stale"] = True
            raw_err = str(bundle["error"]).strip()
            meta["error"] = raw_err
            meta["lastError"] = raw_err
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

GITHUB_RAW_BASE = os.getenv(
    "GITHUB_RAW_BASE",
    "https://raw.githubusercontent.com/oURFo/typhoon-monitor/main/data",
)
REMOTE_CACHE_TTL = float(os.getenv("FLIGHTS_REMOTE_CACHE_TTL", "30"))

_remote_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def load_flights_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        return {"airports": [], "flights": [], "updatedAt": None, "count": 0}
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def merge_tpe_snapshot(data: dict[str, Any], tpe_data: dict[str, Any]) -> dict[str, Any]:
    """主快照缺桃園時，合併 tpe-flights.json。"""
    tpe_rows = tpe_data.get("flights") or []
    if not tpe_rows:
        return data

    others = [f for f in data.get("flights", []) if f.get("airport") != "TPE"]
    by_airport = dict(data.get("byAirport") or {})
    by_airport_direction = dict(data.get("byAirportDirection") or {})
    by_direction = {
        "departure": [
            f for f in (data.get("byDirection") or {}).get("departure", []) if f.get("airport") != "TPE"
        ],
        "arrival": [
            f for f in (data.get("byDirection") or {}).get("arrival", []) if f.get("airport") != "TPE"
        ],
    }

    by_airport.pop("TPE", None)
    by_airport_direction.pop("TPE", None)
    by_airport["TPE"] = (tpe_data.get("byAirport") or {}).get("TPE") or tpe_rows
    tpe_dirs = (tpe_data.get("byAirportDirection") or {}).get("TPE") or {
        "departure": [f for f in tpe_rows if f.get("direction") == "departure"],
        "arrival": [f for f in tpe_rows if f.get("direction") == "arrival"],
    }
    by_airport_direction["TPE"] = tpe_dirs

    tpe_by_dir = tpe_data.get("byDirection") or {}
    if tpe_by_dir:
        by_direction["departure"].extend(tpe_by_dir.get("departure", []))
        by_direction["arrival"].extend(tpe_by_dir.get("arrival", []))
    else:
        by_direction["departure"].extend(tpe_dirs.get("departure", []))
        by_direction["arrival"].extend(tpe_dirs.get("arrival", []))

    airports = [a for a in data.get("airports", []) if a.get("code") != "TPE"]
    tpe_meta = (tpe_data.get("cacheMeta") or {}).get("TPE") or {}
    airports.append(
        {
            "code": "TPE",
            "name": "桃園國際機場",
            "stale": True,
            "error": "合併 tpe-flights.json 快取",
            **tpe_meta,
        }
    )

    cache_meta = {**(data.get("cacheMeta") or {}), **(tpe_data.get("cacheMeta") or {})}
    return {
        **data,
        "flights": [*others, *tpe_rows],
        "byAirport": by_airport,
        "byAirportDirection": by_airport_direction,
        "byDirection": by_direction,
        "cacheMeta": cache_meta,
        "airports": airports,
        "count": len(others) + len(tpe_rows),
    }


def _tpe_in_snapshot(data: dict[str, Any]) -> bool:
    tpe_dirs = (data.get("byAirportDirection") or {}).get("TPE") or {}
    return len(tpe_dirs.get("departure") or []) > 0


async def _fetch_github_json(filename: str, *, bypass_cache: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not bypass_cache and filename in _remote_cache:
        fetched_at, cached = _remote_cache[filename]
        if now - fetched_at < REMOTE_CACHE_TTL:
            return cached

    url = f"{GITHUB_RAW_BASE.rstrip('/')}/{filename}"
    if bypass_cache:
        url = f"{url}?_={int(time.time())}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "TyphoonMonitor/1.0 (+https://github.com/oURFo/typhoon-monitor)",
        "Cache-Control": "no-cache",
    }
    async with async_client(timeout=45.0) as client:
        res = await client.get(url, headers=headers)
        res.raise_for_status()
        payload = res.json()

    if not isinstance(payload, dict):
        raise ValueError(f"{filename} 不是 JSON 物件")
    _remote_cache[filename] = (now, payload)
    return payload


async def fetch_remote_snapshot(*, bypass_cache: bool = False) -> dict[str, Any]:
    """從 GitHub raw 讀取最新 flights.json（Render 正式環境用）。"""
    data = await _fetch_github_json("flights.json", bypass_cache=bypass_cache)
    if _tpe_in_snapshot(data):
        return data
    try:
        tpe_data = await _fetch_github_json("tpe-flights.json", bypass_cache=bypass_cache)
        return merge_tpe_snapshot(data, tpe_data)
    except Exception:  # noqa: BLE001
        return data
