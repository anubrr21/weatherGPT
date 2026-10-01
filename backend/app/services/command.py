import asyncio
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import advisory, cyclones, fieldmap
from app.services.cyclones import bearing_word, inside, km
from app.services.http import TTLCache, get_retry

DATA = Path(__file__).resolve().parent.parent / "data" / "india_towns.json"
RAIN_BANDS = [(204.5, "Extremely heavy", 4), (115.6, "Very heavy", 3), (64.5, "Heavy", 2), (15.6, "Moderate", 1), (2.5, "Light", 0), (0.0, "Dry", 0)]
SEVERITY_SCORE = {"Extreme": 3, "Severe": 2, "Moderate": 1}
MAX_TOWNS = 40
_cache = TTLCache(ttl_s=1200)


@lru_cache(maxsize=1)
def towns() -> list[dict[str, Any]]:
    return json.loads(DATA.read_text(encoding="utf-8"))["towns"] if DATA.exists() else []


def rain_band(mm: float) -> tuple[str, int]:
    for floor, label, level in RAIN_BANDS:
        if mm >= floor:
            return label, level
    return "Dry", 0


def towns_near(lat: float, lon: float, radius_km: float, limit: int = MAX_TOWNS) -> list[dict[str, Any]]:
    pad = radius_km / 100 + 0.5
    found = []
    for town in towns():
        if abs(town["lat"] - lat) > pad or abs(town["lon"] - lon) > pad * 1.2:
            continue
        distance = km((lat, lon), (town["lat"], town["lon"]))
        if distance <= radius_km:
            found.append(town | {"km": round(distance), "direction": bearing_word((lat, lon), (town["lat"], town["lon"])) if distance >= 3 else "here"})
    found.sort(key=lambda t: (-(t["population"] or 0), t["km"]))
    return found[:limit]


def summarise_town(town: dict[str, Any], hourly: dict[str, Any], now: str) -> dict[str, Any]:
    times = hourly["time"]
    start = next((i for i, t in enumerate(times) if t[:13] >= now[:13]), 0)
    rain = [v or 0 for v in hourly["precipitation"]]
    gusts = [v or 0 for v in hourly["wind_gusts_10m"]]
    past = round(sum(rain[max(0, start - 24):start]), 1)
    next24 = rain[start:start + 24]
    next72 = rain[start:start + 72]
    peak_index = max(range(len(next24)), key=lambda i: next24[i]) if next24 else 0
    heat = [advisory.heat_index(t, r) for t, r in zip(hourly["temperature_2m"][start:start + 24], hourly["relative_humidity_2m"][start:start + 24]) if t is not None and r is not None]
    label, level = rain_band(sum(next24))
    gust = max(gusts[start:start + 24], default=0)
    heat_max = max(heat, default=None)
    thunder = sum(1 for c in hourly["weather_code"][start:start + 24] if c in (95, 96, 99))
    score = level + (2 if gust >= 70 else 1 if gust >= 50 else 0) + (2 if (heat_max or 0) >= 54 else 1 if (heat_max or 0) >= 41 else 0) + (1 if thunder >= 3 else 0)
    return town | {
        "rain_past_24h": past, "rain_next_24h": round(sum(next24), 1), "rain_next_72h": round(sum(next72), 1), "rain_band": label,
        "max_hourly_mm": round(max(next24, default=0), 1), "max_hourly_time": times[start + peak_index] if next24 and max(next24) > 0 else None,
        "gust_max": round(gust), "heat_index_max": heat_max, "thunder_hours": thunder, "score": score, "warnings": [],
    }


async def _weather(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
        "latitude": ",".join(str(p["lat"]) for p in points), "longitude": ",".join(str(p["lon"]) for p in points),
        "hourly": "precipitation,wind_gusts_10m,temperature_2m,relative_humidity_2m,weather_code", "current": "temperature_2m",
        "past_days": 1, "forecast_days": 4, "timezone": "auto",
    }, timeout=60)
    data = response.json()
    rows = data if isinstance(data, list) else [data]
    return rows, rows[0]["current"]["time"]


def sitrep(place: str, radius_km: int, summary: dict[str, Any], ranked: list[dict[str, Any]], official: list[dict[str, Any]], storms: list[dict[str, Any]], now: str) -> str:
    when = datetime.fromisoformat(now).strftime("%d %b %Y, %H:%M")
    lines = [f"SITUATION REPORT: {place} and {radius_km} km around", f"Prepared {when} local time by WeatherGPT from official warnings and model forecasts.", ""]
    lines.append("1. OFFICIAL WARNINGS")
    if official:
        for w in official[:8]:
            lines.append(f"   - {w['severity']} {w['event']} ({w['issuer']}), until {w['expires'][11:16] if w.get('expires') else 'further notice'}: {len(w['towns'])} listed towns covered" + (f" ({', '.join(w['towns'][:5])})" if w["towns"] else ""))
    else:
        lines.append("   - None in force for this area.")
    lines += ["", "2. RAINFALL"]
    lines.append(f"   - Next 24 h: {summary['heavy_towns']} of {summary['towns']} towns expect heavy rain or more (64.5 mm+); wettest {summary['wettest']['name']} {summary['wettest']['rain_next_24h']} mm.")
    lines.append(f"   - Last 24 h: wettest {summary['wettest_past']['name']} {summary['wettest_past']['rain_past_24h']} mm.")
    lines += ["", "3. WIND, HEAT AND THUNDERSTORMS"]
    lines.append(f"   - Strongest gusts: {summary['windiest']['name']} {summary['windiest']['gust_max']} km/h.")
    if summary["hottest"]:
        lines.append(f"   - Highest heat index: {summary['hottest']['name']} {summary['hottest']['heat_index_max']:.0f} °C.")
    lines.append(f"   - Thunderstorms forecast at {summary['thunder_towns']} towns.")
    lines += ["", "4. CYCLONES"]
    if storms:
        for s in storms:
            hit = s.get("impact") or {}
            closest = hit.get("closest") or {}
            lines.append(f"   - {s['name']}: {(s['now'].get('grade') or {}).get('label', 'system')}, {hit.get('distance_now_km')} km {hit.get('direction_now')}; closest approach {closest.get('km')} km.")
    else:
        lines.append("   - No active system in the Bay of Bengal or Arabian Sea.")
    lines += ["", "5. PLACES NEEDING ATTENTION"]
    watch = [t for t in ranked if t["score"] > 0][:8]
    if watch:
        for t in watch:
            notes = [f"{t['rain_band'].lower()} rain {t['rain_next_24h']} mm" if t["rain_next_24h"] >= 15.6 else None, f"gusts {t['gust_max']} km/h" if t["gust_max"] >= 50 else None,
                     f"heat index {t['heat_index_max']:.0f} °C" if (t["heat_index_max"] or 0) >= 41 else None, f"{len(t['warnings'])} official warning(s)" if t["warnings"] else None,
                     "thunderstorms" if t["thunder_hours"] >= 3 else None]
            lines.append(f"   - {t['name']} ({t['km']} km {t['direction']}" + (f", pop. {t['population']:,}" if t["population"] else "") + "): " + ", ".join(n for n in notes if n) + ".")
    else:
        lines.append("   - No town is flagged in the next 24 hours.")
    lines += ["", f"People in flagged towns (where population is known): {summary['population_flagged']:,}.", "Verify with IMD, CWC and the State Emergency Operations Centre before acting."]
    return "\n".join(lines)


async def workspace(lat: float, lon: float, radius_km: int = 100, place_name: str = "Selected area") -> dict[str, Any]:
    key = f"{lat:.2f},{lon:.2f}:{radius_km}"

    async def load() -> dict[str, Any]:
        near = towns_near(lat, lon, radius_km)
        if not near:
            return {"available": False, "reason": "No towns found in this radius."}
        (rows, now), warn, storm_data = await asyncio.gather(_weather(near), fieldmap.warnings(), cyclones.storms())
        scanned = [summarise_town(t, r["hourly"], now) for t, r in zip(near, rows)]
        official = []
        for w in warn["warnings"]:
            covered = [t for t in scanned if any(inside((t["lat"], t["lon"]), ring) for ring in w["rings"])]
            centre_in = any(inside((lat, lon), ring) for ring in w["rings"])
            if not covered and not centre_in:
                continue
            for t in covered:
                t["warnings"].append({"event": w["event"], "severity": w["severity"]})
                t["score"] += SEVERITY_SCORE.get(w["severity"] or "", 0)
            official.append({"id": w["id"], "event": w["event"], "severity": w["severity"], "headline": w["headline"], "issuer": (w["issuer"] or "").split("(")[-1].rstrip(")"),
                             "expires": w["expires"], "areas": w["areas"], "towns": [t["name"] for t in covered], "rings": w["rings"]})
        official.sort(key=lambda w: -SEVERITY_SCORE.get(w["severity"] or "", 0))
        ranked = sorted(scanned, key=lambda t: (-t["score"], -t["rain_next_24h"], -(t["population"] or 0)))
        flagged = [t for t in ranked if t["score"] > 0]
        hot = [t for t in scanned if t["heat_index_max"] is not None]
        summary = {
            "towns": len(scanned), "flagged": len(flagged), "population_flagged": sum(t["population"] or 0 for t in flagged), "population_scanned": sum(t["population"] or 0 for t in scanned),
            "heavy_towns": sum(1 for t in scanned if t["rain_next_24h"] >= 64.5), "warned_towns": sum(1 for t in scanned if t["warnings"]),
            "thunder_towns": sum(1 for t in scanned if t["thunder_hours"] > 0),
            "wettest": max(scanned, key=lambda t: t["rain_next_24h"]), "wettest_past": max(scanned, key=lambda t: t["rain_past_24h"]),
            "windiest": max(scanned, key=lambda t: t["gust_max"]), "hottest": max(hot, key=lambda t: t["heat_index_max"]) if hot else None,
            "area_rain_next_24h": round(sum(t["rain_next_24h"] for t in scanned) / len(scanned), 1), "area_rain_past_24h": round(sum(t["rain_past_24h"] for t in scanned) / len(scanned), 1),
        }
        storms = [s | {"impact": cyclones.impact(s, lat, lon)} for s in storm_data["active"]]
        brief_storms = [{"name": s["name"], "now": s["now"], "impact": s["impact"]} for s in storms]
        return {
            "available": True, "generated": now, "radius_km": radius_km, "centre": {"lat": lat, "lon": lon, "name": place_name}, "summary": summary, "towns": ranked,
            "official": official, "storms": brief_storms, "sitrep": sitrep(place_name, radius_km, summary, ranked, official, storms, now),
            "rules": "IMD 24-hour rainfall classes: moderate 15.6 mm, heavy 64.5 mm, very heavy 115.6 mm, extremely heavy 204.5 mm. A town is flagged for heavy rain, gusts of 50 km/h or more, a heat index of 41 °C or more, three or more thunderstorm hours, or an official warning polygon covering it.",
            "source": "Towns and populations from OpenStreetMap; forecasts from Open-Meteo best match; warning polygons from NDMA SACHET (IMD, CWC, SDMAs)",
        }

    return await _cache.get_or_set(key, load)
