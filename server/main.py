"""東亞颱風監測 API 與靜態網站服務。"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import cwa, flights

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="Typhoon Monitor", version="0.1.0")

PUBLIC_DIR = ROOT / "public"
app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/typhoons")
async def get_typhoons(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        items = await cwa.fetch_typhoons()
        return {
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "satellite": cwa.satellite_meta(),
            "typhoons": items,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/typhoon-warnings")
async def get_typhoon_warnings() -> dict:
    try:
        items = await cwa.fetch_typhoon_warnings()
        return {"warnings": items}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/flights")
async def get_flights(
    response: Response,
    airline: str = "",
    number: str = "",
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if airline.strip() or number.strip():
        data = await flights.search_flights(airline, number)
    else:
        data = await flights.fetch_all_flights()
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    return data


@app.get("/api/airports")
async def get_airports() -> dict:
    config = flights.load_airport_config()
    return {
        "airports": [
            {"code": code, "name": item.get("name", code)}
            for code, item in config.items()
            if not code.startswith("_") and isinstance(item, dict)
        ]
    }
