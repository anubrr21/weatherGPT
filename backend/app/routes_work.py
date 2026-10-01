from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services import aviation, city, command, farm, research, sea, weather

router = APIRouter()


async def _place(lat: float, lon: float) -> dict:
    try:
        return await weather.reverse_geocode(lat, lon) | {"lat": lat, "lon": lon}
    except Exception:
        return {"lat": lat, "lon": lon}


@router.get("/api/work/farm")
async def work_farm(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), crops: str | None = Query(None, max_length=200)):
    try:
        return await farm.workspace(lat, lon, crops, await _place(lat, lon))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Farm data unavailable: {exc}") from exc


@router.get("/api/work/sea")
async def work_sea(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    try:
        return await sea.workspace(lat, lon, await _place(lat, lon))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sea data unavailable: {exc}") from exc


@router.get("/api/work/aviation")
async def work_aviation(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), icao: str | None = Query(None, min_length=4, max_length=4)):
    try:
        return await aviation.workspace(lat, lon, icao)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Aviation data unavailable: {exc}") from exc


@router.get("/api/work/city")
async def work_city(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), am: int = Query(9, ge=4, le=12), pm: int = Query(18, ge=13, le=23)):
    try:
        return await city.workspace(lat, lon, am, pm, await _place(lat, lon))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"City data unavailable: {exc}") from exc


@router.get("/api/work/command")
async def work_command(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), radius_km: int = Query(100, ge=30, le=250)):
    place = await _place(lat, lon)
    try:
        return await command.workspace(lat, lon, radius_km, place.get("district") or place.get("name") or "Selected area")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Command board unavailable: {exc}") from exc


@router.get("/api/work/data")
async def work_data(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    return await research.workspace(lat, lon)


@router.get("/api/work/data/export")
async def work_data_export(kind: str = Query(..., pattern="^(forecast|models|climate|observations)$"), lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    try:
        body = await research.export(kind, lat, lon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Export failed: {exc}") from exc
    name = f"weathergpt_{kind}_{lat:.2f}_{lon:.2f}.csv"
    return Response(content=body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})
