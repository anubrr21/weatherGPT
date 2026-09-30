from fastapi import APIRouter, HTTPException, Query

from app.services import cyclones

router = APIRouter()


@router.get("/api/cyclones/live")
async def cyclones_live(lat: float | None = Query(None, ge=-90, le=90), lon: float | None = Query(None, ge=-180, le=180)):
    try:
        return await cyclones.live(lat, lon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cyclone feeds unavailable: {exc}") from exc


@router.get("/api/cyclones/history")
async def cyclones_history(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), radius_km: int = Query(150, ge=25, le=500)):
    return cyclones.near_history(lat, lon, radius_km)


@router.get("/api/cyclones/storm/{sid}")
async def cyclone_storm(sid: str):
    storm = cyclones.storm_detail(sid)
    if storm is None:
        raise HTTPException(status_code=404, detail="Unknown storm")
    return storm


@router.get("/api/cyclones/local")
async def cyclone_local(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    return await cyclones.local_forecast(lat, lon)


@router.get("/api/cyclones/shelters")
async def cyclone_shelters(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), radius_km: int = Query(30, ge=5, le=60)):
    return cyclones.shelters(lat, lon, radius_km)
