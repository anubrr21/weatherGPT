import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import advisory, agent, alerts, providers, weather
from app.services.http import close_client
from app.services.tools import ChatContext


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_client()


app = FastAPI(title="WeatherGPT API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

Lat = Query(..., ge=-90, le=90)
Lon = Query(..., ge=-180, le=180)


async def _guard(coro):
    try:
        return await coro
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream data source failed: {exc}") from exc


@app.get("/api/health")
async def health():
    settings = get_settings()
    return {
        "ok": True,
        "llm": settings.llm_enabled,
        "providers": [
            {"name": cls.name, "model": model, "cooling_s": round(providers.cooling(f"{cls.name}:{model}"))} for cls, model in providers.chain()
        ],
    }


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=2)):
    return await _guard(weather.geocode(q))


@app.get("/api/reverse")
async def reverse(lat: float = Lat, lon: float = Lon):
    return await _guard(weather.reverse_geocode(lat, lon))


@app.get("/api/weather")
async def forecast(lat: float = Lat, lon: float = Lon, model: str = "best_match"):
    return await _guard(weather.forecast(lat, lon, model=model))


@app.get("/api/models")
async def models(lat: float = Lat, lon: float = Lon):
    return await _guard(weather.compare_models(lat, lon))


@app.get("/api/air")
async def air(lat: float = Lat, lon: float = Lon):
    return await _guard(weather.air_quality(lat, lon))


@app.get("/api/climate")
async def climate(lat: float = Lat, lon: float = Lon, month: int | None = Query(None, ge=1, le=12)):
    return await _guard(weather.climate(lat, lon, month=month))


@app.get("/api/alerts")
async def location_alerts(lat: float = Lat, lon: float = Lon):
    place = await weather.reverse_geocode(lat, lon)
    fc = await _guard(weather.forecast(lat, lon))
    return {
        "place": place,
        "official": alerts.alerts_for_place(await alerts.official_alerts(), place),
        "derived": alerts.derived_advisories(fc),
    }


@app.get("/api/insights")
async def insights(lat: float = Lat, lon: float = Lon, role: str = "general", crop: str | None = None, stage: str | None = None):
    fc = await _guard(weather.forecast(lat, lon))
    return advisory.home_insights(role, fc, crop, stage)


@app.get("/api/alerts/india")
async def india_alerts():
    return await alerts.official_alerts()


class Turn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[Turn] = []
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = None
    language: str = "en"
    profile: dict[str, Any] = {}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    ctx = ChatContext(lat=req.lat, lon=req.lon, place_name=req.place_name, language=req.language, profile=req.profile)

    async def stream():
        async for event in agent.chat(req.message, [t.model_dump() for t in req.history], ctx):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
