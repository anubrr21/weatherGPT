from fastapi import APIRouter, HTTPException

from app.services import fieldmap

router = APIRouter()


@router.get("/api/maps/fields")
async def map_fields():
    try:
        return await fieldmap.fields()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Forecast fields unavailable: {exc}") from exc


@router.get("/api/maps/warnings")
async def map_warnings():
    return await fieldmap.warnings()
