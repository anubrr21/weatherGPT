import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import get_settings
from app.db import Session, backend_name, init_db
from app.routes_live import router as live_router
from app.routes_cyclones import router as cyclones_router
from app.routes_lightning import router as lightning_router
from app.routes_verify import router as verify_router
from app.routes_phone import router as phone_router
from app.services import advisory, agent, alerts, ingest, knowledge, lightning, local_stt, local_tts, providers, ratings, trips, voice, weather, wis2
from app.services.fanout import fanout
from app.services.http import close_client
from app.services.tools import ChatContext


@asynccontextmanager
async def lifespan(_: FastAPI):
    role = get_settings().role
    await init_db()
    if role in ("all", "worker"):
        ingest.start()
        wis2.subscriber.start()
    lightning.feed.start()
    if role in ("all", "api"):
        fanout.start()
        asyncio.get_running_loop().run_in_executor(None, local_tts.warm, ["hi", "en"])
        if local_stt.indic.installed():
            asyncio.get_running_loop().run_in_executor(None, local_stt.indic.languages)
    yield
    await fanout.stop()
    await lightning.feed.stop()
    await wis2.subscriber.stop()
    await ingest.stop()
    await close_client()


app = FastAPI(title="WeatherGPT API", version="0.1.0", lifespan=lifespan)
app.include_router(live_router)
app.include_router(phone_router)
app.include_router(cyclones_router)
app.include_router(lightning_router)
app.include_router(verify_router)
app.add_middleware(GZipMiddleware, minimum_size=800, compresslevel=6, exclude_content_types=(*DEFAULT_EXCLUDED_CONTENT_TYPES, "audio/ogg", "audio/wav"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

Lat = Query(..., ge=-90, le=90)
Lon = Query(..., ge=-180, le=180)


def fast_json(data: Any) -> Response:
    return Response(json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")), media_type="application/json")


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
        "knowledge": knowledge.stats(),
        "neural_voice": bool(local_tts.available_languages() or settings.gemini_api_key.strip() or settings.azure_speech_key.strip()),
        "local_voices": local_tts.available_languages(),
        "voice_engines": [name for name, on in (
            ("local", bool(local_tts.available_languages())),
            ("sarvam", bool(settings.sarvam_api_key.strip())),
            ("azure", bool(settings.azure_speech_key.strip())),
            ("gemini", bool(settings.gemini_api_key.strip())),
        ) if on],
        "server_stt": voice.stt_available(),
        "google_ratings": ratings.enabled(),
        "local_stt": local_stt.available(),
        "providers": [
            {"name": cls.name, "model": model, "cooling_s": round(providers.cooling(f"{cls.name}:{model}"))} for cls, model in providers.chain()
        ],
    }


@app.get("/api/ready")
async def ready():
    try:
        async with Session() as s:
            await s.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {type(exc).__name__}") from exc
    return {"ready": True, "role": get_settings().role, "database": backend_name()}


@app.get("/api/geocode")
async def geocode(q: str = Query(..., min_length=2)):
    return await _guard(weather.geocode(q))


@app.get("/api/reverse")
async def reverse(lat: float = Lat, lon: float = Lon):
    return await _guard(weather.reverse_geocode(lat, lon))


@app.get("/api/weather")
async def forecast(lat: float = Lat, lon: float = Lon, model: str = "best_match"):
    fc, observed = await asyncio.gather(_guard(weather.forecast(lat, lon, model=model)), weather.nearest_observation(lat, lon))
    return fast_json({**fc, "observed": observed})


@app.get("/api/models")
async def models(lat: float = Lat, lon: float = Lon):
    return fast_json(await _guard(weather.compare_models(lat, lon)))


@app.get("/api/air")
async def air(lat: float = Lat, lon: float = Lon):
    return fast_json(await _guard(weather.air_quality(lat, lon)))


@app.get("/api/climate")
async def climate(lat: float = Lat, lon: float = Lon, month: int | None = Query(None, ge=1, le=12)):
    return fast_json(await _guard(weather.climate(lat, lon, month=month)))


@app.get("/api/alerts")
async def location_alerts(lat: float = Lat, lon: float = Lon):
    place = await weather.reverse_geocode(lat, lon)
    fc = await _guard(weather.forecast(lat, lon))
    return fast_json({
        "place": place,
        "official": alerts.alerts_for_place(await alerts.official_alerts(), place),
        "derived": alerts.derived_advisories(fc),
    })


@app.get("/api/insights")
async def insights(lat: float = Lat, lon: float = Lon, role: str = "general", crop: str | None = None, stage: str | None = None):
    fc = await _guard(weather.forecast(lat, lon))
    return fast_json(advisory.home_insights(role, fc, crop, stage))


@app.get("/api/satellite/rain")
async def satellite_rain():
    return await _guard(weather.satellite_rain_frames())


@app.get("/api/alerts/india")
async def india_alerts():
    return await alerts.official_alerts()


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1500)
    voice: str = "Kore"
    language: str | None = None
    format: Literal["wav", "opus"] = "wav"


class TripPlace(BaseModel):
    name: str = Field(..., max_length=160)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    district: str | None = None
    state: str | None = None


class TripRequest(BaseModel):
    origin: TripPlace
    destination: TripPlace
    vias: list[TripPlace] = Field(default_factory=list, max_length=8)
    mode: Literal["car", "bike", "bus", "train", "flight", "trek"] = "car"
    depart: datetime | None = None
    rest_stops: bool = False


@app.post("/api/trip")
async def plan_trip(req: TripRequest):
    depart = req.depart
    if depart is not None and depart.tzinfo is None:
        depart = depart.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    try:
        trip = await trips.plan(req.origin.model_dump(), req.destination.model_dump(), req.mode, depart, req.rest_stops, [v.model_dump() for v in req.vias])
    except trips.TripError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Route or weather service failed: {exc}") from exc
    return fast_json(trip | {"briefs": [trips.brief(trip, i) for i in range(len(trip["routes"]))]})


@app.post("/api/tts")
async def tts(req: SpeakRequest):
    try:
        audio, media_type = await voice.synthesize_as(req.text, req.voice, req.language, req.format)
    except voice.VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str | None = Form(None)):
    data = await audio.read()
    if len(data) < 1200:
        raise HTTPException(status_code=400, detail="Recording too short")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Recording too long")
    try:
        return await voice.transcribe(data, audio.filename or "speech.webm", audio.content_type or "audio/webm", language)
    except voice.VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class Turn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[Turn] = []
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = None
    place_label: str | None = None
    language: str = "en"
    profile: dict[str, Any] = {}
    trip: dict[str, Any] | None = None


@app.post("/api/chat")
async def chat(req: ChatRequest):
    ctx = ChatContext(lat=req.lat, lon=req.lon, place_name=req.place_name, place_label=req.place_label, language=req.language, profile=req.profile, trip=req.trip)

    async def stream():
        async for event in agent.chat(req.message, [t.model_dump() for t in req.history], ctx):
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
