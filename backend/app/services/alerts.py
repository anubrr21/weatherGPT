import asyncio
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.services.http import TTLCache, client

CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
SEVERITY_RANK = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1, "Unknown": 0}

_feed_cache = TTLCache(ttl_s=300, max_items=4)
_cap_cache = TTLCache(ttl_s=86400, max_items=4096)
_fetch_limit = asyncio.Semaphore(12)


def _text(node: ET.Element | None, path: str) -> str | None:
    if node is None:
        return None
    found = node.find(path, CAP_NS)
    return found.text.strip() if found is not None and found.text else None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _fetch_cap(link: str, guid: str, fallback_title: str, author: str | None) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        async with _fetch_limit:
            try:
                response = await client().get(link, timeout=15)
                response.raise_for_status()
                root = ET.fromstring(response.content)
            except Exception:
                return None
        infos = root.findall("cap:info", CAP_NS)
        if not infos:
            return None
        english = next((i for i in infos if (_text(i, "cap:language") or "").lower().startswith("en")), infos[0])
        localized = [
            {"language": _text(i, "cap:language"), "headline": _text(i, "cap:headline")}
            for i in infos
            if i is not english and _text(i, "cap:headline")
        ]
        areas = [a for a in (_text(area, "cap:areaDesc") for area in english.findall("cap:area", CAP_NS)) if a]
        return {
            "id": guid,
            "source": "IMD / NDMA SACHET (CAP)",
            "issuer": author,
            "sender": _text(root, "cap:sender"),
            "sent": _text(root, "cap:sent"),
            "event": _text(english, "cap:event"),
            "category": _text(english, "cap:category"),
            "severity": _text(english, "cap:severity") or "Unknown",
            "urgency": _text(english, "cap:urgency"),
            "certainty": _text(english, "cap:certainty"),
            "headline": _text(english, "cap:headline") or fallback_title,
            "description": _text(english, "cap:description"),
            "instruction": _text(english, "cap:instruction"),
            "effective": _text(english, "cap:effective"),
            "expires": _text(english, "cap:expires"),
            "areas": areas,
            "localized": localized,
            "link": link,
        }

    return await _cap_cache.get_or_set(guid, load)


async def _load_feed() -> list[dict[str, Any]]:
    response = await client().get(get_settings().alert_feed_url, timeout=20)
    response.raise_for_status()
    channel = ET.fromstring(response.content).find("channel")
    items = channel.findall("item") if channel is not None else []
    tasks = []
    for item in items:
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link).strip()
        if not link:
            continue
        tasks.append(_fetch_cap(link, guid, (item.findtext("title") or "").strip(), item.findtext("author")))
    parsed = [a for a in await asyncio.gather(*tasks) if a]
    now = datetime.now(timezone.utc)
    live = [a for a in parsed if (_parse_time(a["expires"]) or now) >= now]
    live.sort(key=lambda a: a["sent"] or "", reverse=True)
    live.sort(key=lambda a: -SEVERITY_RANK.get(a["severity"], 0))
    return live


async def official_alerts(fresh: bool = False) -> list[dict[str, Any]]:
    if fresh:
        live = await _load_feed()
        _feed_cache.put("feed", live)
        return live
    try:
        return await _feed_cache.get_or_set("feed", _load_feed)
    except Exception:
        return []


DIRECTIONS = {"purba": "east", "paschim": "west", "uttar": "north", "dakshin": "south", "dakshina": "south", "uttara": "north", "pashchim": "west"}

ALIASES = [
    {"bardhaman", "burdwan", "barddhaman"},
    {"medinipur", "midnapore", "midnapur"},
    {"cooch behar", "coochbehar", "koch bihar"},
    {"darjeeling", "darjiling"},
    {"howrah", "haora"},
    {"hooghly", "hugli"},
    {"kolkata", "calcutta"},
    {"gurugram", "gurgaon"},
    {"nuh", "mewat"},
    {"prayagraj", "allahabad"},
    {"ayodhya", "faizabad"},
    {"bengaluru", "bangalore"},
    {"mysuru", "mysore"},
    {"kalaburagi", "gulbarga"},
    {"belagavi", "belgaum"},
    {"vijayapura", "bijapur"},
    {"shivamogga", "shimoga"},
    {"mangaluru", "mangalore", "dakshina kannada", "south kannada"},
    {"thiruvananthapuram", "trivandrum"},
    {"kozhikode", "calicut"},
    {"thrissur", "trichur"},
    {"kochi", "cochin", "ernakulam"},
    {"alappuzha", "alleppey"},
    {"chennai", "madras"},
    {"tiruchirappalli", "trichy", "tiruchi"},
    {"thoothukudi", "tuticorin"},
    {"puducherry", "pondicherry"},
    {"visakhapatnam", "vizag", "vishakhapatnam", "visakhapatanam"},
    {"vijayawada", "ntr", "bezawada"},
    {"nellore", "sri potti sriramulu nellore", "spsr nellore"},
    {"kadapa", "cuddapah", "ysr", "ysr kadapa"},
    {"anantapur", "ananthapuramu", "anantapuramu"},
    {"odisha", "orissa"},
    {"baleshwar", "balasore"},
    {"kendujhar", "keonjhar"},
    {"mumbai", "bombay", "mumbai suburban"},
    {"pune", "poona"},
    {"vadodara", "baroda"},
    {"ahmedabad", "amdavad"},
    {"varanasi", "banaras", "benares"},
    {"kanpur", "cawnpore"},
    {"guwahati", "kamrup metropolitan", "kamrup metro"},
    {"shimla", "simla"},
    {"new delhi", "delhi", "nct of delhi", "national capital territory of delhi"},
]


def _normalize(value: str | None) -> str:
    ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z ]", " ", ascii_text.lower())
    words = [DIRECTIONS.get(w, w) for w in text.split() if w not in {"district", "dist", "city", "urban", "rural"}]
    return " ".join(words)


def _word(term: str) -> str:
    return f"(?<![a-z]){re.escape(term)}(?![a-z])"


def _expand(name: str) -> set[str]:
    names = {name}
    for group in ALIASES:
        for alias in group:
            if re.search(_word(alias), name):
                names |= {re.sub(_word(alias), other, name) for other in group}
                names |= group
    return names


def _place_tokens(place: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in ("name", "district"):
        norm = _normalize(place.get(key))
        if len(norm) >= 3:
            tokens |= _expand(norm)
            core = re.sub(r"^(east|west|north|south) ", "", norm)
            if core != norm and len(core) >= 4:
                tokens |= {t for t in _expand(core) if len(t) >= 4}
    return tokens


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and re.search(_word(needle), haystack) is not None


def alerts_for_place(alerts: list[dict[str, Any]], place: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = _place_tokens(place)
    states = _expand(_normalize(place.get("state"))) if place.get("state") else set()
    matched = []
    for alert in alerts:
        areas = " | ".join(_normalize(a) for a in alert["areas"])
        haystack = f"{areas} | {_normalize(alert.get('headline'))}"
        sender = _normalize((alert.get("sender") or "").replace("-", " "))
        local = any(_contains(haystack, t) for t in tokens if t not in states)
        state_level = any(_contains(haystack, s) or _contains(sender, s) for s in states)
        if local or state_level:
            matched.append({**alert, "match": "district" if local else "state"})
    matched.sort(key=lambda a: (a["match"] != "district", -SEVERITY_RANK.get(a["severity"], 0)))
    return matched


def _rain_category(mm: float) -> tuple[str, str] | None:
    if mm >= 204.5:
        return "Extremely heavy rainfall", "Extreme"
    if mm >= 115.6:
        return "Very heavy rainfall", "Severe"
    if mm >= 64.5:
        return "Heavy rainfall", "Moderate"
    return None


def derived_advisories(fc: dict[str, Any], elevation: float | None = None) -> list[dict[str, Any]]:
    hilly = (elevation or fc.get("elevation") or 0) >= 1000
    heat_threshold = 30 if hilly else 40
    out: list[dict[str, Any]] = []
    for day in fc.get("daily", [])[:5]:
        d = day["time"]
        rain = day.get("precipitation_sum") or 0
        tmax = day.get("temperature_2m_max")
        tmin = day.get("temperature_2m_min")
        gust = day.get("wind_gusts_10m_max") or 0
        code = day.get("weather_code") or 0
        category = _rain_category(rain)
        if category:
            out.append({"date": d, "event": category[0], "severity": category[1],
                        "detail": f"{rain:.0f} mm forecast in 24 h (IMD threshold ≥64.5 mm heavy, ≥115.6 very heavy, ≥204.5 extremely heavy)."})
        if tmax is not None and tmax >= heat_threshold + 5:
            out.append({"date": d, "event": "Severe heat wave conditions", "severity": "Severe",
                        "detail": f"Max temperature {tmax:.1f} °C. Avoid sun exposure 12–4 pm, hydrate, check on elderly."})
        elif tmax is not None and tmax >= heat_threshold:
            out.append({"date": d, "event": "Heat stress", "severity": "Moderate",
                        "detail": f"Max temperature {tmax:.1f} °C, at or above IMD heat-wave base threshold ({heat_threshold} °C)."})
        if tmin is not None and tmin <= (0 if hilly else 4):
            out.append({"date": d, "event": "Cold wave conditions", "severity": "Moderate",
                        "detail": f"Min temperature {tmin:.1f} °C."})
        if gust >= 88:
            out.append({"date": d, "event": "Damaging winds", "severity": "Severe",
                        "detail": f"Gusts up to {gust:.0f} km/h — secure loose structures, avoid travel."})
        elif gust >= 60:
            out.append({"date": d, "event": "Strong gusty winds", "severity": "Moderate",
                        "detail": f"Gusts up to {gust:.0f} km/h."})
        if code >= 95:
            out.append({"date": d, "event": "Thunderstorm & lightning", "severity": "Moderate" if code == 95 else "Severe",
                        "detail": "Stay indoors during lightning; avoid open fields, trees and water bodies."})
    for hour in fc.get("hourly", [])[:24]:
        vis = hour.get("visibility")
        if vis is not None and vis < 200:
            out.append({"date": hour["time"][:10], "event": "Dense fog", "severity": "Moderate",
                        "detail": f"Visibility near {vis:.0f} m around {hour['time'][11:16]}."})
            break
    for a in out:
        a["source"] = "Model-derived advisory (not an official IMD warning)"
    return out
