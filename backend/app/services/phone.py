import asyncio
import base64
import hashlib
import hmac
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import PhoneMessage, PhoneSubscriber, Session, utcnow
from app.services import alerts as alert_service
from app.services import providers, smart, weather
from app.services.http import TTLCache, client

log = logging.getLogger("weathergpt.phone")

IST = timezone(timedelta(hours=5, minutes=30))
LANGUAGES = {"en": "English", "hi": "Hindi", "bn": "Bengali", "te": "Telugu", "ta": "Tamil", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "or": "Odia", "pa": "Punjabi", "as": "Assamese", "ur": "Urdu"}
LANGUAGE_WORDS = {
    "en": "en", "eng": "en", "english": "en", "hi": "hi", "hin": "hi", "hindi": "hi", "हिंदी": "hi", "हिन्दी": "hi",
    "te": "te", "tel": "te", "telugu": "te", "తెలుగు": "te", "ta": "ta", "tamil": "ta", "தமிழ்": "ta", "bn": "bn", "bengali": "bn", "bangla": "bn", "বাংলা": "bn",
    "mr": "mr", "marathi": "mr", "मराठी": "mr", "gu": "gu", "gujarati": "gu", "ગુજરાતી": "gu", "kn": "kn", "kannada": "kn", "ಕನ್ನಡ": "kn",
    "ml": "ml", "malayalam": "ml", "മലയാളം": "ml", "or": "or", "odia": "or", "oriya": "or", "ଓଡ଼ିଆ": "or", "pa": "pa", "punjabi": "pa", "ਪੰਜਾਬੀ": "pa",
    "as": "as", "assamese": "as", "অসমীয়া": "as", "ur": "ur", "urdu": "ur", "اردو": "ur",
}
COMMANDS = {
    "weather": {"weather", "w", "mausam", "mosam", "मौसम", "వాతావరణం", "வானிலை", "আবহাওয়া", "हवामान", "હવામાન", "ಹವಾಮಾನ", "കാലാവസ്ഥ", "ମୌସମ", "ਮੌਸਮ", "موسم"},
    "join": {"join", "sub", "subscribe", "start", "जुड़ें", "जोड़ें", "shuru"},
    "stop": {"stop", "unsubscribe", "cancel", "band", "बंद", "रोकें", "end", "quit"},
    "yes": {"yes", "y", "haan", "ha", "han", "हाँ", "हां", "ok", "avunu", "ఔను", "ஆம்", "হ্যাঁ", "ho", "होय"},
    "lang": {"lang", "language", "bhasha", "भाषा"},
    "help": {"help", "h", "?", "madad", "मदद", "sahayata", "सहायता"},
}
GSM7 = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€")
PIN = re.compile(r"^\s*(\d{6})\s*$")
_say_cache = TTLCache(ttl_s=7 * 86400)
_pin_cache = TTLCache(ttl_s=30 * 86400)
TWILIO = "https://api.twilio.com/2010-04-01/Accounts/{sid}/{kind}.json"


class PhoneError(Exception):
    pass


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    raise PhoneError("Enter a 10-digit Indian mobile number")


def mask(phone: str) -> str:
    return phone[:3] + " " + phone[3:5] + "xxx xx" + phone[-3:]


def sms_encoding(text: str) -> tuple[str, int]:
    if all(ch in GSM7 or ch in GSM7_EXT for ch in text):
        units = sum(2 if ch in GSM7_EXT else 1 for ch in text)
        return "gsm7", 1 if units <= 160 else -(-units // 153)
    units = sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)
    return "ucs2", 1 if units <= 70 else -(-units // 67)


def fit(text: str, max_segments: int) -> str:
    text = " ".join(text.split())
    while sms_encoding(text)[1] > max_segments:
        cut = max(text.rfind("। ", 0, len(text) - 1), text.rfind(". ", 0, len(text) - 1))
        text = text[: cut + 1].strip() if cut > len(text) // 3 else text[: int(len(text) * 0.9)].rstrip() + "…"
    return text


def parse(text: str) -> tuple[str, str]:
    stripped = " ".join((text or "").strip().split())
    if not stripped:
        return "help", ""
    if PIN.match(stripped):
        return "weather", stripped
    first, _, rest = stripped.partition(" ")
    word = first.lower().strip(".,!:")
    for command, words in COMMANDS.items():
        if word in words:
            return command, rest.strip()
    if word in LANGUAGE_WORDS and not rest:
        return "lang", word
    return "ask", stripped


SCRIPTS = {
    "hi": (0x0900, 0x097F), "mr": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "as": (0x0980, 0x09FF), "pa": (0x0A00, 0x0A7F),
    "gu": (0x0A80, 0x0AFF), "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF), "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F), "ur": (0x0600, 0x06FF),
}
REFUSAL = re.compile(r"\b(sorry|i can(no|\u2019|')t|i am unable|i'm unable|as an ai|cannot (help|assist|comply))\b", re.I)
NUMBER = re.compile(r"\d+")
TOKEN = re.compile(r"\[[A-Z]+\]")


class TranslationError(Exception):
    pass


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text)


def valid_translation(source: str, translated: str, language: str) -> bool:
    if not translated or REFUSAL.search(translated):
        return False
    if sorted(NUMBER.findall(source)) != sorted(NUMBER.findall(_ascii_digits(translated))):
        return False
    if sorted(TOKEN.findall(source)) != sorted(TOKEN.findall(translated)):
        return False
    low, high = SCRIPTS.get(language, (0, 0x10FFFF))
    letters = [ch for ch in TOKEN.sub("", translated) if ch.isalpha()]
    native = sum(1 for ch in letters if low <= ord(ch) <= high)
    if letters and native / len(letters) < 0.4:
        return False
    return len(translated) >= 0.35 * len(source)


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", "", text.strip().strip('"'), flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


async def say(text: str, language: str, **names: str) -> str:
    if language == "en" or language not in LANGUAGES or not text.strip():
        return _fill(text, names)
    key = hashlib.sha1(f"{language}|{text}".encode()).hexdigest()
    prompts = [
        f"You translate messages of WeatherGPT, a public weather information helpline run for farmers and villagers in India, into {LANGUAGES[language]} in its native script. "
        "The text is read aloud on a phone call or sent as an SMS. 'PIN code' means the Indian postal PIN code of a village, never a password. "
        "Translate every sentence in the same order as one paragraph, without lists or line breaks. "
        "Keep all digits as Western digits (0-9), units (°C, mm, km/h, %), times, place names and these words exactly as written: WeatherGPT, IMD, NDMA, JOIN, STOP, YES, WEATHER, LANG, HELP. "
        "Words in square brackets such as [PLACE] are placeholders: copy them unchanged. "
        "Reply with the translation only.",
        f"Translate the text inside <text> tags from English into {LANGUAGES[language]} (native script). It is an announcement of an Indian government-style weather helpline. "
        "Translate all sentences completely, keep every number as written in Western digits, keep English command words in capitals and placeholders in square brackets unchanged. Output only the translated text, no tags.",
    ]

    async def load() -> str:
        for attempt, system in enumerate(prompts):
            message = text if attempt == 0 else f"<text>{text}</text>"
            try:
                raw, _ = await providers.complete(system, message)
            except Exception as exc:
                log.info("translation to %s failed: %s", language, exc)
                continue
            translated = _clean(re.sub(r"</?text>", "", raw))
            if valid_translation(text, translated, language):
                return translated
            log.info("rejected %s translation: %.80s", language, translated)
        raise TranslationError(language)

    try:
        return _fill(await _say_cache.get_or_set(key, load), names)
    except TranslationError:
        return _fill(text, names)


def _fill(text: str, names: dict[str, str]) -> str:
    for token, value in names.items():
        text = text.replace(f"[{token.upper()}]", value)
    return text


async def say_each(sentences: list[str], language: str, **names: str) -> str:
    parts = await asyncio.gather(*(say(sentence, language, **names) for sentence in sentences if sentence.strip()))
    return " ".join(parts)


async def place_from_pin(pin: str) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        response = await client().get(f"https://api.postalpincode.in/pincode/{pin}", timeout=15)
        data = response.json() if response.status_code == 200 else []
        offices = (data[0].get("PostOffice") or []) if data else []
        if not offices:
            return None
        office = offices[0]
        for query in (f"{office['Name']}", office.get("Block") or "", office.get("District") or ""):
            if not query:
                continue
            for hit in await weather.geocode(query):
                if (hit.get("state") or "").lower() == (office.get("State") or "").lower():
                    return hit | {"name": office["Name"], "district": office.get("District") or hit.get("district"), "state": office.get("State"), "pin": pin}
        return None

    try:
        return await _pin_cache.get_or_set(pin, load)
    except Exception as exc:
        log.info("PIN lookup failed for %s: %s", pin, exc)
        return None


async def resolve(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    if PIN.match(text):
        return await place_from_pin(text)
    hits = await weather.geocode(text)
    india = [h for h in hits if (h.get("country_code") or "IN") == "IN"]
    return (india or hits or [None])[0]


def place_of(sub: PhoneSubscriber | None) -> dict[str, Any] | None:
    if not sub or sub.lat is None or sub.lon is None:
        return None
    return {"name": sub.place_name, "district": sub.district, "state": sub.state, "lat": sub.lat, "lon": sub.lon}


async def forecast_text(place: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fc = await weather.forecast(place["lat"], place["lon"])
    now = datetime.fromisoformat(fc["current"]["time"])
    facts = await smart.briefing_facts(fc, place["lat"], place["lon"], now, "general")
    parts = [f"{place['name']} today: {facts.get('condition', '')}, {facts.get('min_temp')}-{facts.get('max_temp')}°C"]
    if facts.get("feels_like_peak") and facts["feels_like_peak"] >= (facts.get("max_temp") or 0) + 2:
        parts.append(f"feels like {facts['feels_like_peak']}°C")
    if facts.get("rain_chance") is not None:
        rain = f"rain chance {facts['rain_chance']}%"
        if (facts.get("rain_mm") or 0) >= 1:
            rain += f", about {facts['rain_mm']:.0f} mm"
        if facts.get("rain_likely_from"):
            rain += f" from {facts['rain_likely_from']}"
        parts.append(rain)
    if (facts.get("max_gust_kmh") or 0) >= 30:
        parts.append(f"gusts {facts['max_gust_kmh']} km/h")
    return ". ".join(parts) + ". -WeatherGPT", facts


async def ask(question: str, place: dict[str, Any] | None, language: str) -> str:
    from app.services import agent
    from app.services.tools import ChatContext

    ctx = ChatContext(lat=place["lat"] if place else None, lon=place["lon"] if place else None, place_name=place["name"] if place else None, place_label=place["name"] if place else None, language=language)
    text = ""
    async for event in agent.chat(question + " (Reply for an SMS: very short.)", [], ctx):
        if event.get("type") == "delta":
            text += event.get("text", "")
    spoken = re.search(r"<speak>(.*?)</speak>", text, re.S)
    answer = spoken.group(1) if spoken else re.sub(r"[*_#>`]|<[^>]+>", "", text)
    return " ".join(answer.split())


async def _twilio(kind: str, data: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    response = await client().post(
        TWILIO.format(sid=settings.twilio_account_sid, kind=kind),
        data=data,
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        timeout=20,
    )
    if response.status_code >= 300:
        raise PhoneError(f"Twilio {kind} failed ({response.status_code}): {response.text[:200]}")
    return response.json()


def provider() -> str:
    settings = get_settings()
    return "twilio" if settings.phone_provider == "twilio" and settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from else "simulator"


async def log_message(phone: str, direction: str, channel: str, text: str, kind: str, status: str, dedup: str | None = None, data: dict[str, Any] | None = None, provider_id: str | None = None) -> PhoneMessage | None:
    encoding, segments = sms_encoding(text) if channel == "sms" else ("audio", 0)
    async with Session() as s:
        if dedup and await s.scalar(select(PhoneMessage.id).where(PhoneMessage.phone == phone, PhoneMessage.dedup_key == dedup)):
            return None
        message = PhoneMessage(phone=phone, direction=direction, channel=channel, kind=kind, text=text, segments=segments, encoding=encoding, provider=provider(), status=status, dedup_key=dedup, data=data or {}, provider_id=provider_id)
        s.add(message)
        await s.commit()
        return message


async def send_sms(phone: str, text: str, kind: str = "reply", dedup: str | None = None, max_segments: int = 3) -> PhoneMessage | None:
    text = fit(text, max_segments)
    if dedup:
        async with Session() as s:
            if await s.scalar(select(PhoneMessage.id).where(PhoneMessage.phone == phone, PhoneMessage.dedup_key == dedup)):
                return None
    provider_id, status = None, "delivered"
    if provider() == "twilio":
        try:
            result = await _twilio("Messages", {"To": phone, "From": get_settings().twilio_from, "Body": text})
            provider_id, status = result.get("sid"), result.get("status", "queued")
        except PhoneError as exc:
            log.warning("sms to %s failed: %s", mask(phone), exc)
            status = "failed"
    return await log_message(phone, "out", "sms", text, kind, status, dedup, provider_id=provider_id)


async def place_call(phone: str, reason: str, data: dict[str, Any], dedup: str | None = None) -> PhoneMessage | None:
    summary = data.get("summary") or reason
    provider_id, status = None, "ringing"
    if provider() == "twilio":
        base = get_settings().public_base_url.rstrip("/")
        if not base:
            status = "failed"
        else:
            query = "&".join(f"{k}={v}" for k, v in {"reason": reason, **{k: v for k, v in data.items() if k in ("alert_id",)}}.items())
            try:
                result = await _twilio("Calls", {"To": phone, "From": get_settings().twilio_from, "Url": f"{base}/api/ivr/twilio?{query}"})
                provider_id, status = result.get("sid"), result.get("status", "queued")
            except PhoneError as exc:
                log.warning("call to %s failed: %s", mask(phone), exc)
                status = "failed"
    return await log_message(phone, "out", "voice", summary, reason, status, dedup, data, provider_id)


async def subscriber(phone: str) -> PhoneSubscriber | None:
    async with Session() as s:
        return await s.get(PhoneSubscriber, phone)


async def save_subscriber(phone: str, **fields: Any) -> PhoneSubscriber:
    async with Session() as s:
        sub = await s.get(PhoneSubscriber, phone) or PhoneSubscriber(phone=phone)
        for key, value in fields.items():
            setattr(sub, key, value)
        sub.updated_at = utcnow()
        s.add(sub)
        await s.commit()
        return sub


def _place_fields(place: dict[str, Any]) -> dict[str, Any]:
    return {"place_name": place.get("name"), "district": place.get("district"), "state": place.get("state"), "lat": place.get("lat"), "lon": place.get("lon")}


async def handle_inbound(phone: str, text: str) -> list[str]:
    await log_message(phone, "in", "sms", text, "inbound", "received")
    sub = await subscriber(phone)
    language = sub.language if sub else "hi"
    command, argument = parse(text)
    replies: list[str] = []

    if command == "stop":
        if sub:
            await save_subscriber(phone, active=False)
        replies.append(await say("You will not get WeatherGPT messages or calls any more. Send JOIN with your village name to start again.", language))
    elif command == "yes":
        if sub and sub.place_name:
            await save_subscriber(phone, confirmed=True, active=True)
            replies.append(await say(f"Confirmed. You will get weather warnings for {sub.place_name} by SMS, a call for severe warnings, and a 6:30 AM summary. Send STOP to end.", language))
        else:
            replies.append(await say("Send JOIN with your village or town name, for example: JOIN Tenali", language))
    elif command == "lang":
        chosen = LANGUAGE_WORDS.get(argument.lower().strip())
        if not chosen:
            replies.append("Send LANG with a language, for example LANG HI, LANG TE, LANG TA, LANG BN, LANG MR, LANG EN")
        else:
            await save_subscriber(phone, language=chosen)
            replies.append(await say(f"Language set to {LANGUAGES[chosen]}.", chosen))
    elif command == "join":
        place = await resolve(argument) if argument else place_of(sub)
        if not place:
            replies.append(await say("Could not find that place. Send JOIN with your village or town name, or your 6-digit PIN code.", language))
        else:
            await save_subscriber(phone, **_place_fields(place), language=language, confirmed=True, active=True, sms=True)
            replies.append(await say(f"Joined for {place['name']}. You will get weather warnings by SMS, a call for severe warnings, and a 6:30 AM summary. Send WEATHER for today, STOP to end.", language))
    elif command == "help":
        replies.append(await say("WeatherGPT: send WEATHER for today, WEATHER <place> for another place, JOIN <place> for warnings, LANG HI to change language, STOP to end. Or ask any weather question.", language))
    elif command == "weather":
        place = await resolve(argument) if argument else place_of(sub)
        if not place:
            replies.append(await say("Send WEATHER with your village or town name, or your 6-digit PIN code. Example: WEATHER Tenali", language))
        else:
            text_en, _ = await forecast_text(place)
            replies.append(await say(text_en, language))
            if not sub:
                replies.append(await say(f"Send JOIN {place['name']} to get warnings for this place.", language))
    else:
        try:
            replies.append(await ask(argument, place_of(sub), language) or await say("Sorry, I could not answer that. Send HELP for options.", language))
        except Exception as exc:
            log.info("sms question failed: %s", exc)
            replies.append(await say("WeatherGPT is busy right now. Please try again in a minute.", language))

    for reply in replies:
        await send_sms(phone, reply)
    return replies


async def invite(phone: str, place: dict[str, Any], language: str, added_by: str) -> PhoneSubscriber:
    existing = await subscriber(phone)
    if existing and existing.confirmed and existing.active:
        return await save_subscriber(phone, **_place_fields(place), added_by=added_by)
    sub = await save_subscriber(phone, **_place_fields(place), language=language, confirmed=False, active=True, added_by=added_by)
    await send_sms(phone, await say(f"WeatherGPT: a family member added this number for weather warnings for {place['name']}. Reply YES to start, STOP to refuse.", language), kind="invite", max_segments=4)
    return sub


def warning_sentence(alert: dict[str, Any], place: str) -> str:
    return f"WeatherGPT warning for {place}: {alert.get('severity', '')} {alert.get('event') or 'weather warning'}. {alert.get('headline', '')}"


async def alert_subscribers(new_alerts: list[dict[str, Any]]) -> dict[str, int]:
    if not new_alerts:
        return {"sms": 0, "calls": 0}
    async with Session() as s:
        subs = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.active.is_(True), PhoneSubscriber.confirmed.is_(True), PhoneSubscriber.lat.is_not(None)))).all()
    sent = calls = 0
    for sub in subs:
        place = place_of(sub)
        for alert in alert_service.alerts_for_place(new_alerts, place):
            if alert.get("match") != "district":
                continue
            content = hashlib.sha1(" ".join((alert.get("headline") or "").lower().split()).encode()).hexdigest()[:20]
            local = next((i["headline"] for i in alert.get("localized") or [] if (i.get("language") or "").split("-")[0].lower() == sub.language and i.get("headline")), None)
            text = local or await say(warning_sentence(alert, sub.place_name), sub.language)
            if sub.sms and await send_sms(sub.phone, text, kind="warning", dedup=f"alert:{content}", max_segments=4):
                sent += 1
            if sub.voice and alert.get("severity") in ("Severe", "Extreme"):
                if await place_call(sub.phone, "warning", {"alert_id": alert["id"], "summary": text, "severity": alert.get("severity")}, dedup=f"call:{content}"):
                    calls += 1
    return {"sms": sent, "calls": calls}


def ref(phone: str) -> str:
    return hashlib.sha1(f"weathergpt|{phone}".encode()).hexdigest()[:12]


async def drill(phone: str) -> dict[str, Any]:
    sub = await subscriber(phone)
    if not sub or not sub.active or sub.lat is None:
        raise PhoneError("This number has not joined warnings yet. Send JOIN with your village or PIN code first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    text = await say("WeatherGPT practice warning for [PLACE]. This is only a test of warning SMS and calls. No action is needed.", sub.language, place=sub.place_name or "")
    sms = await send_sms(phone, text, kind="drill", dedup=f"drill:{stamp}")
    call = await place_call(phone, "warning", {"summary": text, "severity": "Drill", "drill": True}, dedup=f"drill-call:{stamp}") if sub.voice else None
    return {"sms": bool(sms), "call": call.id if call else None}


async def morning_briefings() -> int:
    async with Session() as s:
        subs = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.active.is_(True), PhoneSubscriber.confirmed.is_(True), PhoneSubscriber.briefing.is_(True), PhoneSubscriber.lat.is_not(None)))).all()
    sent = 0
    for sub in subs:
        place = place_of(sub)
        try:
            fc = await weather.forecast(place["lat"], place["lon"])
        except Exception:
            continue
        now = datetime.fromisoformat(fc["current"]["time"])
        if not smart.briefing_due(now, "06:30", window_min=20):
            continue
        text_en, _ = await forecast_text(place)
        if await send_sms(sub.phone, await say(text_en, sub.language), kind="briefing", dedup=f"briefing:{now:%Y-%m-%d}"):
            sent += 1
    return sent


def valid_twilio_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    token = get_settings().twilio_auth_token
    if not token:
        return False
    payload = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()).decode()
    return bool(signature) and hmac.compare_digest(expected, signature)
