"""東亞颱風監測 API 與靜態網站服務。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cwa, flights
from .http_client import async_client

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="Typhoon Monitor", version="0.1.0")

PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
app.mount("/static", StaticFiles(directory=PUBLIC_DIR), name="static")
if DATA_DIR.is_dir():
    app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        PUBLIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


def _no_store_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


@app.get("/api/health")
async def health(response: Response) -> dict[str, str]:
    _no_store_headers(response)
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/typhoons")
async def get_typhoons(response: Response) -> dict:
    _no_store_headers(response)
    try:
        items = await cwa.fetch_typhoons()
        satellite = await cwa.resolve_satellite_meta()
        if satellite.get("url"):
            satellite = {**satellite, "url": "/api/satellite/image"}
        return {
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "satellite": satellite,
            "typhoons": items,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/satellite/image")
async def get_satellite_image(response: Response) -> Response:
    """代理 CWA/JMA 衛星圖，避免跨域並與 API 座標一致。"""
    _no_store_headers(response)
    try:
        meta = await cwa.resolve_satellite_meta()
        image_url = meta.get("url")
        if not image_url:
            raise RuntimeError("無衛星圖 URL")
        async with async_client(timeout=45.0) as client:
            res = await client.get(
                image_url,
                headers={"User-Agent": "TyphoonMonitor/1.0"},
                follow_redirects=True,
            )
            res.raise_for_status()
        media_type = res.headers.get("content-type", "image/jpeg")
        return Response(content=res.content, media_type=media_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/typhoon-warnings")
async def get_typhoon_warnings() -> dict:
    try:
        items = await cwa.fetch_typhoon_warnings()
        return {"warnings": items}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/flights/snapshot")
async def get_flights_snapshot(response: Response, fresh: bool = False) -> dict:
    """正式網站前端讀取：代理 GitHub 最新 flights.json，避免 CDN／瀏覽器快取。"""
    _no_store_headers(response)
    try:
        return await flights.fetch_remote_snapshot(bypass_cache=fresh)
    except Exception as exc:  # noqa: BLE001
        snapshot = flights.load_flights_snapshot()
        if snapshot.get("flights"):
            return snapshot
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/flights")
async def get_flights(
    response: Response,
    airline: str = "",
    number: str = "",
    destination: str = "",
) -> dict:
    """篩選版；優先遠端快照，本機無資料時讀 repo 內 JSON。"""
    _no_store_headers(response)
    try:
        snapshot = await flights.fetch_remote_snapshot()
    except Exception:  # noqa: BLE001
        snapshot = flights.load_flights_snapshot()
    rows = snapshot.get("flights", [])
    if airline.strip() or number.strip() or destination.strip():
        rows = flights.filter_flights(rows, airline, number, destination)
    return {
        "updatedAt": snapshot.get("updatedAt"),
        "airports": snapshot.get("airports", []),
        "flights": rows,
        "count": len(rows),
    }


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
