import asyncio
import json
import math
from datetime import timedelta

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import Alert, Observation, Session, Subscription, utcnow
from app.services import alerts as alert_service
from app.services import ingest, weather, wis2
from app.services.fanout import fanout
from app.services.http import TTLCache, coord_key
from app.services.realtime import hub

router = APIRouter()


class PlaceIn(BaseModel):
    name: str = Field(..., max_length=160)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    district: str | None = Field(None, max_length=160)
    state: str | None = Field(None, max_length=160)


class SubscriptionIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    places: list[PlaceIn] = Field(default_factory=list, max_length=20)


@router.put("/api/subscriptions")
async def put_subscriptions(body: SubscriptionIn):
    unique = {(round(p.lat, 3), round(p.lon, 3)): p for p in body.places}
    async with Session() as s:
        await s.execute(delete(Subscription).where(Subscription.client_id == body.client_id))
        for (lat, lon), p in unique.items():
            s.add(Subscription(client_id=body.client_id, name=p.name, district=p.district, state=p.state, lat=lat, lon=lon))
        await s.commit()
    await fanout.publish([body.client_id])
    return {"subscribed": len(unique)}


@router.get("/api/alerts/history")
async def alert_history(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), days: int = Query(7, ge=1, le=90)):
    place = await weather.reverse_geocode(lat, lon)
    since = utcnow() - timedelta(days=days)
    async with Session() as s:
        rows = (await s.scalars(select(Alert).where(Alert.first_seen_at >= since).order_by(Alert.sent.desc()))).all()
    matched = alert_service.alerts_for_place([ingest.alert_payload(r) | {"first_seen": ingest.iso(r.first_seen_at)} for r in rows], place)
    now = utcnow()
    for a in matched:
        expires = a.get("expires")
        a["active"] = expires is None or expires >= ingest.iso(now)
    return {"place": place, "days": days, "count": len(matched), "alerts": matched}


_nearby_cache = TTLCache(ttl_s=60)
OBS_COLUMNS = (Observation.station, Observation.name, Observation.lat, Observation.lon, Observation.observed_at, Observation.temp_c, Observation.wind_kmh, Observation.weather)


@router.get("/api/observations/nearby")
async def observations_nearby(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180), hours: int = Query(24, ge=1, le=168)):
    async def load() -> dict:
        since = utcnow() - timedelta(hours=hours)
        rows = []
        async with Session() as s:
            for span in (1.5, 4, 12):
                rows = (await s.execute(select(*OBS_COLUMNS).where(
                    Observation.observed_at >= since,
                    Observation.lat.between(lat - span, lat + span),
                    Observation.lon.between(lon - span, lon + span),
                ))).all()
                if rows:
                    break
        if not rows:
            return {"station": None, "series": []}

        def km(o) -> float:
            p1, p2 = math.radians(lat), math.radians(o.lat)
            a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(o.lon - lon) / 2) ** 2
            return 6371 * 2 * math.asin(math.sqrt(a))

        nearest = min(rows, key=km)
        series = sorted((o for o in rows if o.station == nearest.station), key=lambda o: o.observed_at)
        return {
            "station": nearest.station,
            "name": nearest.name,
            "distance_km": round(km(nearest)),
            "series": [{"time": ingest.iso(o.observed_at), "temp_c": o.temp_c, "wind_kmh": o.wind_kmh, "weather": o.weather} for o in series],
        }

    return await _nearby_cache.get_or_set(coord_key(lat, lon, "nearby", hours), load)


@router.get("/api/system/status")
async def system_status():
    return {
        "role": get_settings().role,
        **await ingest.status(),
        "fanout": fanout.status(),
        "realtime": hub.stats(),
        "wis2": await wis2.subscriber.status(),
    }


@router.get("/api/wis2/status")
async def wis2_status():
    return await wis2.subscriber.status()


@router.websocket("/ws")
async def live(socket: WebSocket, client_id: str = Query(..., min_length=8, max_length=64)):
    await socket.accept()
    await hub.join(client_id, socket)
    try:
        await socket.send_text(json.dumps({"type": "hello", "server_time": ingest.iso(utcnow())}))
        await ingest.notify_client(client_id)
        while True:
            try:
                message = await asyncio.wait_for(socket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await socket.send_text(json.dumps({"type": "ping"}))
                continue
            if message == "ping":
                await socket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.leave(client_id, socket)
