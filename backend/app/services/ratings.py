import asyncio
import difflib
import logging
import re
from typing import Any

from app.config import get_settings
from app.services.http import TTLCache, client

log = logging.getLogger("weathergpt.ratings")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.id,places.displayName,places.rating,places.userRatingCount,places.googleMapsUri,places.location"
MATCH_RADIUS_M = 300
PRIORITY = {"hotel": 0, "motel": 0, "services": 1, "restaurant": 1, "rest_area": 2, "fast_food": 2, "cafe": 3, "guest_house": 3, "fuel": 4}

_cache = TTLCache(ttl_s=24 * 3600)
_gate = asyncio.Semaphore(6)
stats = {"looked_up": 0, "matched": 0, "errors": 0, "last_error": None}


def enabled() -> bool:
    return bool(get_settings().google_maps_api_key.strip())


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def similar(a: str, b: str) -> float:
    x, y = _words(a), _words(b)
    if not x or not y:
        return 0.0
    if x in y or y in x:
        return 1.0
    return difflib.SequenceMatcher(None, x, y).ratio()


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    from app.services.trips import haversine

    return haversine(a, b)


def best_match(place: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = []
    for c in candidates:
        loc = c.get("location") or {}
        if "latitude" not in loc:
            continue
        distance = _distance_m((place["lat"], place["lon"]), (loc["latitude"], loc["longitude"]))
        name = (c.get("displayName") or {}).get("text") or ""
        score = similar(place["name"], name)
        if distance <= MATCH_RADIUS_M and score >= 0.55:
            scored.append((score - distance / 3000, c))
    return max(scored, key=lambda item: item[0])[1] if scored else None


async def lookup(place: dict[str, Any]) -> dict[str, Any] | None:
    key = f"{place['name'].lower()}:{place['lat']:.4f}:{place['lon']:.4f}"

    async def load() -> dict[str, Any] | None:
        body = {
            "textQuery": place["name"],
            "maxResultCount": 3,
            "languageCode": "en",
            "locationBias": {"circle": {"center": {"latitude": place["lat"], "longitude": place["lon"]}, "radius": float(MATCH_RADIUS_M)}},
        }
        headers = {"X-Goog-Api-Key": get_settings().google_maps_api_key.strip(), "X-Goog-FieldMask": FIELDS}
        async with _gate:
            response = await client().post(SEARCH_URL, json=body, headers=headers, timeout=15)
        stats["looked_up"] += 1
        if response.status_code != 200:
            stats["errors"] += 1
            stats["last_error"] = f"{response.status_code}: {response.text[:200]}"
            raise RuntimeError(stats["last_error"])
        match = best_match(place, response.json().get("places") or [])
        if not match or match.get("rating") is None:
            return None
        stats["matched"] += 1
        return {"rating": match["rating"], "count": match.get("userRatingCount") or 0, "url": match.get("googleMapsUri"), "name": (match.get("displayName") or {}).get("text")}

    try:
        return await _cache.get_or_set(key, load)
    except Exception as exc:
        log.info("google rating lookup failed for %s: %s", place["name"], exc)
        return None


async def enrich(places: list[dict[str, Any]], limit: int = 30) -> int:
    if not enabled() or not places:
        return 0
    ordered = sorted(places, key=lambda p: (not p.get("near_break", False), PRIORITY.get(p["kind"], 5), p.get("km", 0)))[:limit]
    results = await asyncio.gather(*(lookup(p) for p in ordered))
    for place, rating in zip(ordered, results):
        if rating:
            place["google"] = rating
    return sum(1 for r in results if r)
