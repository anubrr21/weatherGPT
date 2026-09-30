from fastapi import APIRouter, HTTPException, Query

from app.services import verify

router = APIRouter()


@router.get("/api/verify")
async def verify_scorecard(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), days: int = Query(10, ge=5, le=30)):
    try:
        return await verify.scorecard(lat, lon, days)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Verification data unavailable: {exc}") from exc
