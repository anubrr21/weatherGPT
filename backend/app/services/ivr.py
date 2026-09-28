import hashlib
import io
import logging
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

import av
import numpy as np

from app.services import advisory, local_tts, phone, voice, weather
from app.services import alerts as alert_service
from app.services.http import TTLCache

log = logging.getLogger("weathergpt.ivr")

MENU_LANGUAGES = ["hi", "te", "en", "bn", "mr", "ml", "ur", "ta", "kn", "gu"]
OPTION_TEXT = {
    "hi": "हिंदी के लिए {n} दबाएँ।",
    "te": "తెలుగు కోసం {n} నొక్కండి.",
    "en": "For English, press {n}.",
    "bn": "বাংলার জন্য {n} টিপুন।",
    "mr": "मराठीसाठी {n} दाबा.",
    "ml": "മലയാളത്തിന് {n} അമർത്തുക.",
    "ur": "اردو کے لیے {n} دبائیں۔",
    "ta": "தமிழுக்கு {n} அழுத்தவும்.",
    "kn": "ಕನ್ನಡಕ್ಕಾಗಿ {n} ಒತ್ತಿರಿ.",
    "gu": "ગુજરાતી માટે {n} દબાવો.",
}
RATE = 16000

_audio = TTLCache(ttl_s=24 * 3600)
_sessions = TTLCache(ttl_s=45 * 60)


@dataclass
class Call:
    id: str
    phone: str
    language: str | None = None
    place: dict[str, Any] | None = None
    stage: str = "language"
    reason: str | None = None
    alert_id: str | None = None
    misses: int = 0
    last: dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    text: str
    audio: str
    gather: int | None = None
    timeout: int = 7
    hangup: bool = False

    def json(self, call: Call) -> dict[str, Any]:
        return {"call_id": call.id, "stage": call.stage, "text": self.text, "audio_url": f"/api/ivr/audio/{self.audio}.wav", "gather": self.gather, "timeout": self.timeout, "hangup": self.hangup, "language": call.language}


def languages() -> list[str]:
    ready = set(local_tts.available_languages())
    return [code for code in MENU_LANGUAGES if code in ready][:9]


def _pcm(wav_bytes: bytes) -> np.ndarray:
    container = av.open(io.BytesIO(wav_bytes))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
    chunks = []
    for frame in container.decode(audio=0):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    container.close()
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)


def _wav(samples: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype(np.int16).tobytes())
    return buffer.getvalue()


async def _speak(parts: list[tuple[str, str]]) -> str:
    key = hashlib.sha1(repr(parts).encode()).hexdigest()[:24]

    async def load() -> bytes:
        pause = np.zeros(int(RATE * 0.35), dtype=np.int16)
        pieces = []
        for text, language in parts:
            try:
                pieces += [_pcm(await voice.synthesize(text, language=language)), pause]
            except Exception as exc:
                log.warning("ivr tts failed for %s: %s", language, exc)
        return _wav(np.concatenate(pieces) if pieces else pause)

    await _audio.get_or_set(key, load)
    return key


async def audio(key: str) -> bytes | None:
    try:
        return await _audio.get_or_set(key, _missing)
    except KeyError:
        return None


async def _missing() -> bytes:
    raise KeyError("audio expired")


async def _say(call: Call, english: str, gather: int | None = None, hangup: bool = False, timeout: int = 7) -> Step:
    text = await phone.say(english, call.language or "en")
    return Step(text, await _speak([(text, call.language or "en")]), gather, timeout, hangup)


async def _say_each(call: Call, sentences: list[str], gather: int | None = None, hangup: bool = False, timeout: int = 7, **names: str) -> Step:
    text = await phone.say_each(sentences, call.language or "en", **names)
    return Step(text, await _speak([(text, call.language or "en")]), gather, timeout, hangup)


async def _language_menu(call: Call) -> Step:
    call.stage = "language"
    options = languages()
    parts = [(OPTION_TEXT[code].format(n=i + 1), code) for i, code in enumerate(options)]
    intro = [("WeatherGPT मौसम सेवा में आपका स्वागत है।", "hi")] if "hi" in options else [("Welcome to the WeatherGPT weather service.", "en")]
    return Step(" ".join(t for t, _ in intro + parts), await _speak(intro + parts), gather=1)


async def _main_menu(call: Call, prefix: str = "") -> Step:
    call.stage = "menu"
    where = call.place["name"] if call.place else "your area"
    district = (call.place or {}).get("district") or ""
    sentences = [prefix, "Press 1 for today's weather in [PLACE].", "Press 2 for official warnings.", "Press 3 for farming advice.", "Press 4 to get warnings on this phone by SMS and calls.", "Press 5 to change your place.", "Press 9 to change language."]
    return await _say_each(call, sentences, gather=1, place=where, district=district)


async def _ask_pin(call: Call, retry: bool = False) -> Step:
    call.stage = "pin"
    sentences = ["That PIN code was not found." if retry else "", "Please type the 6 digit PIN code of your village or town."]
    return await _say_each(call, sentences, gather=6, timeout=12)


def _spoken_number(value: float | None) -> str:
    return "unknown" if value is None else str(int(round(value)))


async def _weather(call: Call) -> Step:
    place = call.place
    fc = await weather.forecast(place["lat"], place["lon"])
    from app.services import smart

    now = datetime.fromisoformat(fc["current"]["time"])
    facts = await smart.briefing_facts(fc, place["lat"], place["lon"], now, "general")
    parts = [f"Weather for {place['name']} today: {facts.get('condition', '').lower()}, between {_spoken_number(facts.get('min_temp'))} and {_spoken_number(facts.get('max_temp'))} degrees."]
    if facts.get("feels_like_peak"):
        parts.append(f"It will feel like {_spoken_number(facts['feels_like_peak'])} degrees at the hottest time.")
    if facts.get("rain_chance") is not None:
        rain = f"The chance of rain is {facts['rain_chance']} percent"
        if facts.get("rain_likely_from"):
            rain += f", most likely from {facts['rain_likely_from']}"
        parts.append(rain + ".")
    if (facts.get("max_gust_kmh") or 0) >= 30:
        parts.append(f"Wind gusts up to {facts['max_gust_kmh']} kilometres an hour.")
    parts.append("Press 1 to hear it again, or 0 for the main menu.")
    call.stage = "weather"
    return await _say(call, " ".join(parts), gather=1)


async def _warnings(call: Call) -> Step:
    official = await alert_service.official_alerts()
    matched = [a for a in alert_service.alerts_for_place(official, call.place) if a.get("match") == "district"][:2]
    call.stage = "warnings"
    if not matched:
        return await _say(call, f"There are no official IMD or NDMA warnings for {call.place['name']} right now. Press 0 for the main menu.", gather=1)
    spoken = " ".join(f"{a.get('severity', '')} {a.get('event') or 'warning'}: {a.get('headline', '')}" for a in matched)
    return await _say(call, f"Official warnings for {call.place['name']}. {spoken} Press 1 to repeat, or 0 for the main menu.", gather=1)


async def _farming(call: Call) -> Step:
    fc = await weather.forecast(call.place["lat"], call.place["lon"])
    farm = advisory.farm_advisory(fc)
    windows = farm["spray"]["windows"][:1]
    parts = []
    if windows:
        start, end = windows[0]["start"][11:16], windows[0]["end"][11:16]
        day = "today" if windows[0]["start"][:10] == fc["current"]["time"][:10] else "tomorrow"
        parts.append(f"The next good time to spray is {day} from {start} to {end}.")
    else:
        parts.append("There is no good time to spray in the next two days because of rain, wind or heat.")
    parts.append(farm["irrigation"]["advice"].replace("—", ","))
    if farm["heavy_rain_days"]:
        parts.append("Heavy rain is expected this week, so keep drains open and harvested grain covered.")
    parts.append("Press 1 to repeat, or 0 for the main menu.")
    call.stage = "farming"
    return await _say(call, " ".join(parts), gather=1)


async def _warning_call(call: Call) -> Step:
    from sqlalchemy import select

    from app.db import PhoneMessage, Session

    async with Session() as s:
        message = await s.scalar(select(PhoneMessage).where(PhoneMessage.phone == call.phone, PhoneMessage.channel == "voice", PhoneMessage.kind == "warning").order_by(PhoneMessage.id.desc()))
    text = message.text if message else await phone.say("This is WeatherGPT with an official weather warning for your area.", call.language or "hi")
    call.stage = "warning"
    follow = await phone.say("Press 1 to hear it again. Press 2 for today's weather. Press 8 to stop these calls.", call.language or "hi")
    return Step(f"{text} {follow}", await _speak([(text, call.language or "hi"), (follow, call.language or "hi")]), gather=1)


async def start(phone_number: str, reason: str | None = None, alert_id: str | None = None, call_id: str | None = None) -> tuple[Call, Step]:
    sub = await phone.subscriber(phone_number)
    call = Call(id=call_id or uuid.uuid4().hex, phone=phone_number, language=sub.language if sub else None, place=phone.place_of(sub), reason=reason, alert_id=alert_id)
    if reason == "warning":
        call.language = call.language or "hi"
        step = await _warning_call(call)
    elif call.language:
        step = await _main_menu(call, "Welcome to WeatherGPT.") if call.place else await _ask_pin(call)
    else:
        step = await _language_menu(call)
    call.last = step.json(call)
    _sessions.put(call.id, call)
    return call, step


async def session(call_id: str) -> Call | None:
    try:
        return await _sessions.get_or_set(call_id, _missing)
    except KeyError:
        return None


async def advance(call: Call, digits: str | None) -> Step:
    digits = (digits or "").strip()
    if not digits:
        call.misses += 1
        if call.misses >= 3:
            return await _say(call, "Thank you for calling WeatherGPT. Goodbye.", hangup=True)
        return await _repeat(call)
    call.misses = 0
    if call.stage == "language":
        options = languages()
        if digits.isdigit() and 1 <= int(digits) <= len(options):
            call.language = options[int(digits) - 1]
            if await phone.subscriber(call.phone):
                await phone.save_subscriber(call.phone, language=call.language)
            return await _main_menu(call) if call.place else await _ask_pin(call)
        return await _language_menu(call)
    if call.stage == "pin":
        place = await phone.place_from_pin(digits) if len(digits) == 6 else None
        if not place:
            return await _ask_pin(call, retry=True)
        call.place = place
        if await phone.subscriber(call.phone):
            await phone.save_subscriber(call.phone, **phone._place_fields(place))
        return await _main_menu(call, "Your place is [PLACE], [DISTRICT] district." if place.get("district") else "Your place is [PLACE].")
    if call.stage == "warning":
        if digits == "1":
            return await _warning_call(call)
        if digits == "2" and call.place:
            return await _weather(call)
        if digits == "8":
            await phone.save_subscriber(call.phone, voice=False)
            return await _say(call, "You will not get warning calls any more. Warnings will still come by SMS. Goodbye.", hangup=True)
        return await _say(call, "Thank you. Stay safe. Goodbye.", hangup=True)
    if call.stage in ("weather", "warnings", "farming") and digits == "1":
        return await {"weather": _weather, "warnings": _warnings, "farming": _farming}[call.stage](call)
    if digits == "0" or call.stage != "menu":
        return await _main_menu(call)
    if digits == "1":
        return await _weather(call)
    if digits == "2":
        return await _warnings(call)
    if digits == "3":
        return await _farming(call)
    if digits == "4":
        await phone.save_subscriber(call.phone, **phone._place_fields(call.place), language=call.language or "hi", confirmed=True, active=True, sms=True, voice=True)
        await phone.send_sms(call.phone, await phone.say(f"WeatherGPT: you joined weather warnings for {call.place['name']}. Send WEATHER for today, STOP to end.", call.language or "hi"), kind="confirm")
        return await _main_menu(call, "Done. You will get warnings on this phone.")
    if digits == "5":
        return await _ask_pin(call)
    if digits == "9":
        return await _language_menu(call)
    return await _main_menu(call)


async def _repeat(call: Call) -> Step:
    if call.stage == "language":
        return await _language_menu(call)
    if call.stage == "pin":
        return await _ask_pin(call)
    if call.stage == "warning":
        return await _warning_call(call)
    return await _main_menu(call)


async def respond(call_id: str | None, phone_number: str, digits: str | None, reason: str | None = None, alert_id: str | None = None) -> dict[str, Any]:
    call = await session(call_id) if call_id else None
    if call is None:
        call, step = await start(phone_number, reason, alert_id, call_id)
    else:
        step = await advance(call, digits)
    call.last = step.json(call)
    return call.last


def twiml(step: dict[str, Any], base: str, action: str) -> str:
    play = f"<Play>{escape(base + step['audio_url'])}</Play>"
    if step["hangup"]:
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{play}<Hangup/></Response>'
    gather = f'<Gather input="dtmf" numDigits="{step["gather"]}" timeout="{step["timeout"]}" action="{escape(action)}" method="POST">{play}</Gather>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{gather}<Redirect method="POST">{escape(action)}</Redirect></Response>'
