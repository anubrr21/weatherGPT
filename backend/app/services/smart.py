import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import Notice, NotifyPrefs, Session, Subscription, utcnow
from app.services import alerts as alert_service
from app.services import providers, weather
from app.services.http import TTLCache
from app.services.wmo import describe

log = logging.getLogger("weathergpt.smart")

SEVERITY = {"Info": 0, "Minor": 1, "Moderate": 2, "Severe": 3, "Extreme": 4}
URGENT = {"Severe", "Extreme"}
ALL_KINDS = ("official", "rain_soon", "storm", "heavy_rain", "heat", "wind", "fog", "briefing")
ICON = {"official": "⚠️", "rain_soon": "🌧️", "storm": "⛈️", "heavy_rain": "🌧️", "heat": "🌡️", "wind": "💨", "fog": "🌫️", "briefing": "☀️"}
CHANNEL = {"official": "warnings", "rain_soon": "nowcast", "storm": "nowcast", "briefing": "briefing"}
DAILY_CAP = 6
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "te": "Telugu", "ta": "Tamil", "mr": "Marathi", "gu": "Gujarati",
    "kn": "Kannada", "ml": "Malayalam", "or": "Odia", "pa": "Punjabi", "as": "Assamese", "ur": "Urdu",
}
_text_cache = TTLCache(ttl_s=6 * 3600)


@dataclass
class Signal:
    kind: str
    severity: str
    key: str
    facts: dict[str, Any] = field(default_factory=dict)


def _clock(value: str | None) -> tuple[int, int] | None:
    if not value or not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    hours, minutes = int(value[:2]), int(value[3:])
    return (hours, minutes) if hours < 24 and minutes < 60 else None


def in_quiet_hours(now: datetime, quiet_from: str | None, quiet_to: str | None) -> bool:
    start, end = _clock(quiet_from), _clock(quiet_to)
    if not start or not end or start == end:
        return False
    minute = now.hour * 60 + now.minute
    a, b = start[0] * 60 + start[1], end[0] * 60 + end[1]
    return a <= minute < b if a < b else minute >= a or minute < b


def briefing_due(now: datetime, briefing_at: str | None, window_min: int = 20) -> bool:
    at = _clock(briefing_at)
    if not at:
        return False
    start = now.replace(hour=at[0], minute=at[1], second=0, microsecond=0)
    return start <= now < start + timedelta(minutes=window_min)


def _local(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _bucket(moment: datetime, hours: int) -> str:
    return f"{moment:%Y-%m-%d}:{moment.hour // hours}"


def rain_rate_label(mm_per_hour: float) -> str:
    if mm_per_hour >= 35:
        return "very heavy"
    if mm_per_hour >= 7.6:
        return "heavy"
    if mm_per_hour >= 2.5:
        return "moderate"
    return "light"


def detect(fc: dict[str, Any], slots: list[dict[str, Any]], now: datetime) -> list[Signal]:
    signals: list[Signal] = []
    upcoming = [s for s in slots if s.get("precipitation") is not None and _local(s["time"]) >= now - timedelta(minutes=15)]
    if upcoming and (upcoming[0]["precipitation"] or 0) < 0.1:
        for i, slot in enumerate(upcoming[1:9], start=1):
            if (slot["precipitation"] or 0) >= 0.3:
                start = _local(slot["time"])
                window = upcoming[i:i + 4]
                rate = max((s["precipitation"] or 0) for s in window) * 4
                stormy = any((s.get("weather_code") or 0) >= 95 for s in window)
                kind = "storm" if stormy else "rain_soon"
                label = rain_rate_label(rate)
                severity = "Severe" if stormy or label == "very heavy" else "Moderate" if label == "heavy" else "Info"
                minutes = max(5, int((start - now).total_seconds() // 60))
                signals.append(Signal(kind, severity, f"{kind}:{_bucket(start, 3)}", {
                    "starts_in_minutes": minutes, "starts_at": f"{start:%H:%M}", "intensity": label, "peak_mm_per_hour": round(rate, 1),
                    "thunder": stormy,
                }))
                break
    hourly = [h for h in fc.get("hourly", []) if _local(h["time"]) >= now.replace(minute=0, second=0, microsecond=0)]
    next6, next12, next14 = hourly[:6], hourly[:12], hourly[:14]
    if not any(s.kind == "storm" for s in signals):
        storm = next((h for h in next6 if (h.get("weather_code") or 0) >= 95), None)
        if storm:
            at = _local(storm["time"])
            signals.append(Signal("storm", "Severe" if storm["weather_code"] >= 96 else "Moderate", f"storm:{_bucket(at, 6)}", {
                "starts_at": f"{at:%H:%M}", "condition": describe(storm["weather_code"])["label"], "rain_chance": storm.get("precipitation_probability"),
            }))
    days = {d["time"]: d for d in fc.get("daily", [])}
    today, tomorrow = f"{now:%Y-%m-%d}", f"{now + timedelta(days=1):%Y-%m-%d}"
    for day_key, eligible in ((today, now.hour < 20), (tomorrow, now.hour >= 17)):
        day = days.get(day_key)
        if not day or not eligible:
            continue
        category = alert_service._rain_category(day.get("precipitation_sum") or 0)
        if category:
            signals.append(Signal("heavy_rain", category[1], f"heavy_rain:{day_key}", {
                "day": "today" if day_key == today else "tomorrow", "rain_mm": round(day["precipitation_sum"]), "category": category[0],
                "rain_chance": day.get("precipitation_probability_max"),
            }))
    if 6 <= now.hour < 11:
        rest_of_day = [h for h in hourly if h["time"].startswith(today) and h.get("apparent_temperature") is not None]
        if rest_of_day:
            peak = max(rest_of_day, key=lambda h: h["apparent_temperature"])
            hilly = (fc.get("elevation") or 0) >= 1000
            threshold = 35 if hilly else 41
            if peak["apparent_temperature"] >= threshold:
                signals.append(Signal("heat", "Severe" if peak["apparent_temperature"] >= threshold + 5 else "Moderate", f"heat:{today}", {
                    "feels_like_peak": round(peak["apparent_temperature"]), "peak_at": f"{_local(peak['time']):%H:%M}",
                    "max_temp": round(days.get(today, {}).get("temperature_2m_max") or peak.get("temperature_2m") or 0),
                }))
    gusty = [h for h in next12 if (h.get("wind_gusts_10m") or 0) >= 50]
    if gusty:
        worst = max(gusty, key=lambda h: h["wind_gusts_10m"])
        at = _local(worst["time"])
        signals.append(Signal("wind", "Severe" if worst["wind_gusts_10m"] >= 75 else "Moderate", f"wind:{_bucket(at, 12)}", {
            "gust_kmh": round(worst["wind_gusts_10m"]), "at": f"{at:%H:%M}",
        }))
    if now.hour >= 18 or now.hour < 6:
        foggy = next((h for h in next14 if h.get("visibility") is not None and h["visibility"] < 200), None)
        if foggy:
            at = _local(foggy["time"])
            signals.append(Signal("fog", "Moderate", f"fog:{at:%Y-%m-%d}", {"visibility_m": round(foggy["visibility"]), "from": f"{at:%H:%M}"}))
    return signals


def _spray_window(hours: list[dict[str, Any]]) -> str | None:
    run: list[dict[str, Any]] = []
    for h in hours:
        hour = _local(h["time"]).hour
        ok = 6 <= hour <= 17 and (h.get("precipitation_probability") or 0) < 30 and (h.get("wind_speed_10m") or 0) < 15
        run = run + [h] if ok else []
        if len(run) >= 3:
            return f"{_local(run[0]['time']):%H:%M}–{_local(run[-1]['time']) + timedelta(hours=1):%H:%M}"
    return None


async def briefing_facts(fc: dict[str, Any], lat: float, lon: float, now: datetime, role: str) -> dict[str, Any]:
    today = f"{now:%Y-%m-%d}"
    day = next((d for d in fc.get("daily", []) if d["time"] == today), (fc.get("daily") or [{}])[0])
    hours = [h for h in fc.get("hourly", []) if h["time"].startswith(today)]
    feels = max((h["apparent_temperature"] for h in hours if h.get("apparent_temperature") is not None), default=None)
    rainy = [h for h in hours if (h.get("precipitation_probability") or 0) >= 50]
    facts: dict[str, Any] = {
        "condition": describe(day.get("weather_code") or 0)["label"],
        "min_temp": round(day.get("temperature_2m_min") or 0), "max_temp": round(day.get("temperature_2m_max") or 0),
        "feels_like_peak": round(feels) if feels is not None else None,
        "rain_chance": day.get("precipitation_probability_max"), "rain_mm": round(day.get("precipitation_sum") or 0, 1),
        "rain_likely_from": f"{_local(rainy[0]['time']):%H:%M}" if rainy else None,
        "max_gust_kmh": round(day.get("wind_gusts_10m_max") or 0), "uv_max": day.get("uv_index_max"),
    }
    try:
        air = await weather.air_quality(lat, lon)
        if air.get("india_naqi") is not None:
            facts["air_quality"] = f"NAQI {air['india_naqi']} ({air.get('india_naqi_band')})"
    except Exception:
        pass
    if role == "farmer":
        facts["spray_window"] = _spray_window(hours) or "none today"
    if role == "fisher":
        try:
            sea = await weather.marine(lat, lon)
            if sea.get("available"):
                facts["max_wave_height_m"] = (sea.get("daily") or [{}])[0].get("wave_height_max")
        except Exception:
            pass
    return {k: v for k, v in facts.items() if v is not None}


def _fallback(kind: str, place: str, facts: dict[str, Any]) -> tuple[str, str]:
    if kind == "rain_soon":
        return f"Rain in about {facts['starts_in_minutes']} min at {place}", f"{facts['intensity'].capitalize()} rain expected from {facts['starts_at']}. Take in washing, cover produce, avoid starting a long trip."
    if kind == "storm":
        when = f"in about {facts['starts_in_minutes']} min" if "starts_in_minutes" in facts else f"from {facts['starts_at']}"
        return f"Thunderstorm {when} at {place}", "Lightning risk. Stay indoors, keep away from trees, open fields and water, and unplug appliances."
    if kind == "heavy_rain":
        return f"{facts['category']} {facts['day']} at {place}", f"About {facts['rain_mm']} mm forecast. Avoid low-lying roads, clear drains, and keep phones charged."
    if kind == "heat":
        return f"Feels like {facts['feels_like_peak']}°C today at {place}", f"Peak around {facts['peak_at']}. Avoid the sun 12–4 pm, drink water often, and check on elderly people."
    if kind == "wind":
        return f"Gusts up to {facts['gust_kmh']} km/h at {place}", f"Strongest around {facts['at']}. Secure loose sheets and hoardings, park away from trees."
    if kind == "fog":
        return f"Dense fog tonight at {place}", f"Visibility may drop to {facts['visibility_m']} m from {facts['from']}. Drive slowly with low-beam lights."
    if kind == "briefing":
        rain = f", rain chance {facts['rain_chance']}%" if facts.get("rain_chance") is not None else ""
        return f"Today at {place}: {facts.get('condition', '')}", f"{facts.get('min_temp')}–{facts.get('max_temp')}°C{rain}. Feels like up to {facts.get('feels_like_peak', facts.get('max_temp'))}°C."
    return f"Weather update for {place}", json.dumps(facts, ensure_ascii=False)[:180]


def _parse_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data.get("title") and data.get("body") else None


async def compose(kind: str, place: str, facts: dict[str, Any], language: str, role: str, crops: list[Any], extra: list[Signal] | None = None) -> tuple[str, str, str]:
    others = [{"kind": s.kind, **s.facts} for s in extra or []]
    key = hashlib.sha1(json.dumps([kind, place, facts, others, language, role, crops], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    async def load() -> tuple[str, str, str]:
        system = (
            "You write push notifications for WeatherGPT, an Indian weather assistant used by farmers, fishers and city people. "
            "Use only the facts given, never invent numbers, places or official warnings. Reply with JSON only: "
            '{"title": "...", "body": "..."}. Title: at most 55 characters, no emoji. Body: at most 170 characters, '
            "one or two short sentences with the key numbers and exactly one concrete action suited to the reader. "
            f"Write entirely in {LANGUAGE_NAMES.get(language, 'English')} using its native script. Translate every word, including weather condition names, "
            "severity words and the official warning text; only numbers, units and place names may stay as they are."
        )
        reader = f"Reader: a {role}" + (f" growing {', '.join(str(c.get('name', c)) if isinstance(c, dict) else str(c) for c in crops)}" if crops else "")
        message = json.dumps({"kind": kind, "place": place, "facts": facts, "also": others, "reader": reader}, ensure_ascii=False)
        try:
            text, label = await providers.complete(system, message)
            parsed = _parse_json(text)
            if parsed:
                return str(parsed["title"]).strip()[:80], str(parsed["body"]).strip()[:260], label
        except Exception as exc:
            log.info("notification composer fell back to template: %s", exc)
        title, body = _fallback(kind, place, facts)
        return title, body, "template"

    return await _text_cache.get_or_set(key, load)


async def _prefs(client_ids: list[str]) -> dict[str, NotifyPrefs]:
    async with Session() as s:
        rows = (await s.scalars(select(NotifyPrefs).where(NotifyPrefs.client_id.in_(client_ids)))).all()
    found = {p.client_id: p for p in rows}
    return {cid: found.get(cid) or NotifyPrefs(client_id=cid, language="en", role="general", crops=[], briefing_at="06:30", quiet_from="22:00", quiet_to="06:00", kinds=[]) for cid in client_ids}


def _allowed(prefs: NotifyPrefs, kind: str) -> bool:
    return not prefs.kinds or kind in prefs.kinds


async def _sent_today(client_id: str) -> int:
    since = utcnow() - timedelta(hours=24)
    async with Session() as s:
        return await s.scalar(select(func.count()).select_from(Notice).where(Notice.client_id == client_id, Notice.created_at >= since, Notice.severity.not_in(URGENT))) or 0


async def _store(client_id: str, kind: str, severity: str, title: str, body: str, place: dict[str, Any], data: dict[str, Any], dedup: str) -> Notice | None:
    async with Session() as s:
        exists = await s.scalar(select(Notice.id).where(Notice.client_id == client_id, Notice.dedup_key == dedup))
        if exists:
            return None
        notice = Notice(
            client_id=client_id, kind=kind, severity=severity, title=f"{ICON.get(kind, '')} {title}".strip()[:200], body=body,
            place_name=place["name"], lat=place["lat"], lon=place["lon"], data=data, dedup_key=dedup[:160],
        )
        s.add(notice)
        await s.commit()
        return notice


async def _places() -> dict[tuple[float, float], dict[str, Any]]:
    async with Session() as s:
        subs = (await s.scalars(select(Subscription).order_by(Subscription.id))).all()
    grouped: dict[tuple[float, float], dict[str, Any]] = {}
    for sub in subs:
        key = (round(sub.lat, 2), round(sub.lon, 2))
        entry = grouped.setdefault(key, {"name": sub.name, "district": sub.district, "state": sub.state, "lat": sub.lat, "lon": sub.lon, "clients": []})
        if sub.client_id not in entry["clients"]:
            entry["clients"].append(sub.client_id)
    return grouped


async def run(force_client: str | None = None, force_kinds: tuple[str, ...] = ()) -> list[Notice]:
    places = await _places()
    if force_client:
        places = {k: v | {"clients": [force_client]} for k, v in places.items() if force_client in v["clients"]}
    created: list[Notice] = []
    all_clients = sorted({c for p in places.values() for c in p["clients"]})
    prefs = await _prefs(all_clients) if all_clients else {}
    primary: dict[str, tuple[float, float]] = {}
    for key, place in places.items():
        for client in place["clients"]:
            primary.setdefault(client, key)
    for key, place in places.items():
        try:
            fc = await weather.forecast(place["lat"], place["lon"])
            slots = await weather.nowcast(place["lat"], place["lon"])
        except Exception as exc:
            log.info("smart notifications skipped %s: %s", place["name"], exc)
            continue
        now = _local(fc["current"]["time"])
        signals = detect(fc, slots, now)
        for client in place["clients"]:
            pref = prefs[client]
            chosen = [s for s in signals if _allowed(pref, s.kind) or s.kind in force_kinds]
            if chosen:
                chosen.sort(key=lambda s: SEVERITY.get(s.severity, 0), reverse=True)
                lead = chosen[0]
                urgent = lead.severity in URGENT
                quiet = in_quiet_hours(now, pref.quiet_from, pref.quiet_to)
                if urgent or force_kinds or (not quiet and await _sent_today(client) < DAILY_CAP):
                    title, body, writer = await compose(lead.kind, place["name"], lead.facts, pref.language, pref.role, pref.crops, chosen[1:])
                    dedup = "|".join(sorted(s.key for s in chosen))
                    notice = await _store(client, lead.kind, lead.severity, title, body, place, {"facts": lead.facts, "also": [s.kind for s in chosen[1:]], "writer": writer}, dedup)
                    if notice:
                        created.append(notice)
            wants_briefing = "briefing" in force_kinds or (_allowed(pref, "briefing") and briefing_due(now, pref.briefing_at))
            if primary.get(client) == key and wants_briefing:
                facts = await briefing_facts(fc, place["lat"], place["lon"], now, pref.role)
                title, body, writer = await compose("briefing", place["name"], facts, pref.language, pref.role, pref.crops)
                notice = await _store(client, "briefing", "Info", title, body, place, {"facts": facts, "writer": writer}, f"briefing:{now:%Y-%m-%d}" + (f":{now:%H%M}" if force_kinds else ""))
                if notice:
                    created.append(notice)
    return created


def notice_payload(n: Notice) -> dict[str, Any]:
    return {
        "id": n.id, "kind": n.kind, "severity": n.severity, "title": n.title, "body": n.body,
        "place": {"name": n.place_name, "lat": n.lat, "lon": n.lon}, "data": n.data or {},
        "created_at": (n.created_at if n.created_at.tzinfo else n.created_at.replace(tzinfo=timezone.utc)).isoformat(),
        "read": n.read_at is not None, "channel": CHANNEL.get(n.kind, "alerts"),
    }


def _official_text(alert: dict[str, Any], language: str) -> str | None:
    for item in alert.get("localized") or []:
        if (item.get("language") or "").split("-")[0].lower() == language and item.get("headline"):
            return item["headline"]
    return None


async def official(new_alerts: list[dict[str, Any]]) -> list[Notice]:
    if not new_alerts:
        return []
    places = await _places()
    prefs = await _prefs(sorted({c for p in places.values() for c in p["clients"]}))
    created: list[Notice] = []
    seen: set[tuple[str, str]] = set()
    for place in places.values():
        for alert in alert_service.alerts_for_place(new_alerts, place):
            content = " ".join((alert.get("headline") or "").lower().split())
            for client in place["clients"]:
                pref = prefs[client]
                if not _allowed(pref, "official") or (client, content) in seen:
                    continue
                seen.add((client, content))
                severity = alert.get("severity") or "Moderate"
                title = f"{severity} · {alert.get('event') or 'Weather warning'} — {place['name']}"
                body = alert.get("headline") or ""
                if pref.language != "en":
                    official_text = _official_text(alert, pref.language) or body
                    facts = {"event": alert.get("event"), "severity": severity, "official_text": official_text, "issuer": alert.get("issuer") or alert.get("sender"), "valid_until": alert.get("expires")}
                    title, body, _ = await compose("official", place["name"], facts, pref.language, pref.role, pref.crops)
                    body = _official_text(alert, pref.language) or body
                notice = await _store(
                    client, "official", severity, title, body, place,
                    {"alert_id": alert["id"], "event": alert.get("event"), "issuer": alert.get("issuer") or alert.get("sender"), "expires": alert.get("expires"), "original": alert.get("headline")},
                    f"official:{hashlib.sha1(content.encode()).hexdigest()[:24]}",
                )
                if notice:
                    created.append(notice)
    return created


async def deliver(notices: list[Notice]) -> dict[str, int]:
    if not notices:
        return {"created": 0, "pushed": 0}
    from app.services.fanout import fanout
    from app.services.push import push

    payloads = [notice_payload(n) | {"client_id": n.client_id} for n in notices]
    pushed = await push.deliver(payloads)
    if pushed:
        async with Session() as s:
            for n in await s.scalars(select(Notice).where(Notice.id.in_(pushed))):
                n.pushed = True
            await s.commit()
    await fanout.publish(sorted({n.client_id for n in notices}))
    return {"created": len(notices), "pushed": len(pushed)}


async def stream(client_id: str) -> int:
    from app.services.realtime import hub

    if not hub.online(client_id):
        return 0
    async with Session() as s:
        pending = (await s.scalars(select(Notice).where(Notice.client_id == client_id, Notice.streamed.is_(False)).order_by(Notice.id))).all()
        sent = 0
        for n in pending:
            if await hub.send(client_id, {"type": "notice", "notice": notice_payload(n)}):
                n.streamed = True
                sent += 1
        await s.commit()
    return sent

