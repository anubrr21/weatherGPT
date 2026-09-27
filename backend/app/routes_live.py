import asyncio
import json
import math
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.config import get_settings
from app.db import Alert, Device, Notice, NotifyPrefs, Observation, Session, Subscription, utcnow
from app.services import alerts as alert_service
from app.services import ingest, smart, weather, wis2
from app.services.fanout import fanout
from app.services.http import TTLCache, coord_key
from app.services.push import push
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


class DeviceIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    token: str = Field(..., min_length=20, max_length=512)
    platform: str = Field("android", pattern="^(android|ios|web)$")


class DeviceOut(BaseModel):
    token: str = Field(..., min_length=20, max_length=512)


class ClientIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)


@router.post("/api/devices")
async def register_device(body: DeviceIn):
    async with Session() as s:
        device = await s.get(Device, body.token)
        if device is None:
            s.add(Device(token=body.token, client_id=body.client_id, platform=body.platform))
        else:
            device.client_id = body.client_id
            device.platform = body.platform
            device.last_seen_at = utcnow()
        await s.commit()
    return {"registered": True, "push": push.enabled}


@router.post("/api/devices/unregister")
async def unregister_device(body: DeviceOut):
    async with Session() as s:
        await s.execute(delete(Device).where(Device.token == body.token))
        await s.commit()
    return {"registered": False}


@router.post("/api/devices/test")
async def test_push(body: ClientIn):
    return await push.test(body.client_id)


class PrefsIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    language: str = Field("en", max_length=8)
    role: str = Field("general", max_length=32)
    crops: list[Any] = Field(default_factory=list, max_length=12)
    briefing_at: str | None = Field("06:30", pattern=r"^\d{2}:\d{2}$")
    quiet_from: str | None = Field("22:00", pattern=r"^\d{2}:\d{2}$")
    quiet_to: str | None = Field("06:00", pattern=r"^\d{2}:\d{2}$")
    kinds: list[str] = Field(default_factory=list, max_length=12)


class ReadIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    ids: list[int] = Field(default_factory=list, max_length=500)
    all: bool = False


class TestNoticeIn(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    kind: str = Field("briefing", pattern="^(briefing|rain_soon|storm|heavy_rain|heat|wind|fog)$")


@router.put("/api/notifications/prefs")
async def put_prefs(body: PrefsIn):
    kinds = [k for k in body.kinds if k in smart.ALL_KINDS]
    async with Session() as s:
        prefs = await s.get(NotifyPrefs, body.client_id) or NotifyPrefs(client_id=body.client_id)
        prefs.language, prefs.role, prefs.crops = body.language, body.role, body.crops
        prefs.briefing_at, prefs.quiet_from, prefs.quiet_to, prefs.kinds = body.briefing_at, body.quiet_from, body.quiet_to, kinds
        prefs.updated_at = utcnow()
        s.add(prefs)
        await s.commit()
    return {"saved": True, "kinds": kinds or list(smart.ALL_KINDS)}


@router.get("/api/notifications")
async def list_notifications(client_id: str = Query(..., min_length=8, max_length=64), limit: int = Query(50, ge=1, le=200)):
    async with Session() as s:
        rows = (await s.scalars(select(Notice).where(Notice.client_id == client_id).order_by(Notice.id.desc()).limit(limit))).all()
        unread = await s.scalar(select(func.count()).select_from(Notice).where(Notice.client_id == client_id, Notice.read_at.is_(None)))
    return {"unread": unread or 0, "notices": [smart.notice_payload(n) for n in rows]}


@router.post("/api/notifications/read")
async def mark_read(body: ReadIn):
    async with Session() as s:
        query = update(Notice).where(Notice.client_id == body.client_id, Notice.read_at.is_(None))
        if not body.all:
            query = query.where(Notice.id.in_(body.ids or [-1]))
        result = await s.execute(query.values(read_at=utcnow()))
        await s.commit()
    return {"marked": result.rowcount or 0}


@router.post("/api/notifications/test")
async def test_notice(body: TestNoticeIn):
    created = await smart.run(force_client=body.client_id, force_kinds=(body.kind,))
    result = await smart.deliver(created)
    return result | {"kinds": [n.kind for n in created], "note": None if created else f"no {body.kind} conditions in the forecast right now"}


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
        "push": push.status(),
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
