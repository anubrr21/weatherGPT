from fastapi import APIRouter, HTTPException, Query

from app.services import aviation, farm, sea, weather

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
