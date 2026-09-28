from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import PhoneMessage, PhoneSubscriber, Session
from app.services import ivr, phone

router = APIRouter()


class SimSms(BaseModel):
    phone: str = Field(..., max_length=20)
    text: str = Field(..., min_length=1, max_length=480)


class SimCall(BaseModel):
    phone: str = Field(..., max_length=20)
    call_id: str | None = Field(None, max_length=64)
    digits: str | None = Field(None, max_length=12)
    reason: str | None = Field(None, pattern="^(warning)$")
    message_id: int | None = None


class FamilyPhone(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    phone: str = Field(..., max_length=20)
    name: str = Field(..., max_length=160)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    district: str | None = None
    state: str | None = None
    language: str = Field("hi", max_length=8)


class FamilyRemove(BaseModel):
    client_id: str = Field(..., min_length=8, max_length=64)
    ref: str = Field(..., min_length=12, max_length=12)


class SimDrill(BaseModel):
    phone: str = Field(..., max_length=20)


def _number(raw: str) -> str:
    try:
        return phone.normalize_phone(raw)
    except phone.PhoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _message(m: PhoneMessage) -> dict[str, Any]:
    return {
        "id": m.id, "direction": m.direction, "channel": m.channel, "kind": m.kind, "text": m.text, "segments": m.segments,
        "encoding": m.encoding, "status": m.status, "provider": m.provider, "created_at": m.created_at.isoformat(), "data": m.data or {},
    }


@router.post("/api/phone/sim/sms")
async def sim_sms(body: SimSms):
    number = _number(body.phone)
    replies = await phone.handle_inbound(number, body.text)
    return {"phone": number, "replies": replies}


@router.get("/api/phone/sim/thread")
async def sim_thread(number: str = Query(..., alias="phone"), limit: int = Query(60, ge=1, le=200)):
    number = _number(number)
    async with Session() as s:
        rows = (await s.scalars(select(PhoneMessage).where(PhoneMessage.phone == number).order_by(PhoneMessage.id.desc()).limit(limit))).all()
        sub = await s.get(PhoneSubscriber, number)
    return {
        "phone": number,
        "provider": phone.provider(),
        "subscriber": None if not sub else {"place": sub.place_name, "district": sub.district, "language": sub.language, "confirmed": sub.confirmed, "active": sub.active, "voice": sub.voice},
        "messages": [_message(m) for m in reversed(rows)],
    }


@router.post("/api/phone/sim/call")
async def sim_call(body: SimCall):
    number = _number(body.phone)
    if body.message_id is not None:
        async with Session() as s:
            ringing = await s.get(PhoneMessage, body.message_id)
            if ringing and ringing.phone == number and ringing.status == "ringing":
                ringing.status = "answered"
                await s.commit()
    return await ivr.respond(body.call_id, number, body.digits, body.reason)


@router.get("/api/ivr/audio/{key}.wav")
async def ivr_audio(key: str):
    data = await ivr.audio(key)
    if data is None:
        raise HTTPException(status_code=404, detail="Audio expired")
    return Response(content=data, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/api/phone/family")
async def add_family_phone(body: FamilyPhone):
    number = _number(body.phone)
    place = {"name": body.name, "lat": body.lat, "lon": body.lon, "district": body.district, "state": body.state}
    sub = await phone.invite(number, place, body.language, body.client_id)
    return {"phone": phone.mask(number), "ref": phone.ref(number), "confirmed": sub.confirmed, "provider": phone.provider()}


@router.get("/api/phone/family")
async def list_family_phones(client_id: str = Query(..., min_length=8, max_length=64)):
    async with Session() as s:
        rows = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.added_by == client_id))).all()
    return {"phones": [{"phone": phone.mask(r.phone), "ref": phone.ref(r.phone), "place": r.place_name, "language": r.language, "confirmed": r.confirmed} for r in rows if r.active]}


@router.post("/api/phone/family/remove")
async def remove_family_phone(body: FamilyRemove):
    async with Session() as s:
        rows = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.added_by == body.client_id, PhoneSubscriber.active.is_(True)))).all()
        sub = next((r for r in rows if phone.ref(r.phone) == body.ref), None)
        if sub:
            sub.active = False
            await s.commit()
    return {"removed": sub is not None}


@router.post("/api/phone/sim/drill")
async def sim_drill(body: SimDrill):
    if phone.provider() != "simulator":
        raise HTTPException(status_code=409, detail="Drills are only sent in simulator mode")
    try:
        return await phone.drill(_number(body.phone))
    except phone.PhoneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _twilio_form(request: Request) -> dict[str, str]:
    form = {k: str(v) for k, v in (await request.form()).items()}
    base = get_settings().public_base_url.rstrip("/")
    url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not phone.valid_twilio_signature(url, form, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return form


@router.post("/api/sms/twilio")
async def twilio_sms(request: Request):
    form = await _twilio_form(request)
    number = _number(form.get("From", ""))
    await phone.handle_inbound(number, form.get("Body", ""))
    return Response(content='<?xml version="1.0" encoding="UTF-8"?><Response/>', media_type="application/xml")


@router.post("/api/ivr/twilio")
async def twilio_voice(request: Request, reason: str | None = None, alert_id: str | None = None):
    form = await _twilio_form(request)
    call_id = form.get("CallSid")
    caller = form.get("To") if form.get("Direction", "").startswith("outbound") else form.get("From")
    step = await ivr.respond(call_id, _number(caller or ""), form.get("Digits"), reason, alert_id)
    base = get_settings().public_base_url.rstrip("/")
    return Response(content=ivr.twiml(step, base, f"{base}/api/ivr/twilio"), media_type="application/xml")


@router.get("/api/phone/status")
async def phone_status():
    async with Session() as s:
        subscribers = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.active.is_(True)))).all()
    return {
        "provider": phone.provider(),
        "sms_number": get_settings().twilio_from or None,
        "subscribers": len(subscribers),
        "confirmed": sum(1 for s in subscribers if s.confirmed),
        "ivr_languages": ivr.languages(),
        "note": None if phone.provider() == "twilio" else "Simulator mode: messages and calls are delivered to the phone simulator at /phone. Real SMS in India needs a provider account and DLT registration of the sender ID and templates.",
    }

