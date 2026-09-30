from fastapi import APIRouter, HTTPException, Query

from app.services import lightning

router = APIRouter()


@router.get("/api/lightning/live")
async def lightning_live(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), radius_km: int = Query(300, ge=10, le=600), minutes: int = Query(60, ge=5, le=180)):
    return await lightning.live(lat, lon, radius_km, minutes)


@router.get("/api/lightning/risk")
async def lightning_risk(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    try:
        grid, look = await lightning.risk_grid(lat, lon), await lightning.outlook(lat, lon)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Forecast unavailable: {exc}") from exc
    return {"grid": grid, "outlook": look}
