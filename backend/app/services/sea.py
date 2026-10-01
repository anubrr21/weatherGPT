import asyncio
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import alerts as alert_service
from app.services.http import TTLCache, coord_key, get_retry

MARINE = "https://marine-api.open-meteo.com/v1/marine"
FORECAST = "https://api.open-meteo.com/v1/forecast"
MARINE_VARS = "wave_height,wave_direction,wave_period,wind_wave_height,swell_wave_height,swell_wave_direction,swell_wave_period,ocean_current_velocity,ocean_current_direction,sea_surface_temperature,sea_level_height_msl"
WIND_VARS = "wind_speed_10m,wind_gusts_10m,wind_direction_10m,visibility,precipitation,weather_code,is_day"
DAYS = 5
BOATS: dict[str, dict[str, Any]] = {
    "small": {"label": "Country boat / catamaran", "caution": (1.0, 30), "nogo": (1.5, 40)},
    "motor": {"label": "Motorised fibre boat", "caution": (1.5, 35), "nogo": (2.5, 50)},
    "trawler": {"label": "Mechanised trawler", "caution": (2.5, 45), "nogo": (3.5, 60)},
}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
SEA_WORDS = re.compile(r"fisher|cyclon|depression|squall|high wave|swell|surge|rough sea|sea condition|tidal", re.I)
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODIC = 29.530588853
_cache = TTLCache(ttl_s=1800)


def compass(deg: float | None) -> str | None:
    return None if deg is None else COMPASS[round(deg / 22.5) % 16]


def verdict(boat: str, wave: float | None, gust: float | None, thunder: bool = False, visibility_m: float | None = None) -> tuple[str, list[str]]:
    spec = BOATS[boat]
    wave, gust = wave or 0.0, gust or 0.0
    reasons = []
    level = 0
    if wave >= spec["nogo"][0]:
        level, reasons = 2, reasons + [f"waves {wave:.1f} m"]
    elif wave >= spec["caution"][0]:
        level, reasons = max(level, 1), reasons + [f"waves {wave:.1f} m"]
    if gust >= spec["nogo"][1]:
        level, reasons = 2, reasons + [f"gusts {gust:.0f} km/h"]
    elif gust >= spec["caution"][1]:
        level, reasons = max(level, 1), reasons + [f"gusts {gust:.0f} km/h"]
    if thunder:
        level, reasons = max(level, 1), reasons + ["thunderstorm"]
    if visibility_m is not None and visibility_m < 1000:
        level, reasons = max(level, 1), reasons + ["poor visibility"]
    return ["GO", "CAUTION", "NO-GO"][level], reasons


def tides(times: list[str], levels: list[float | None]) -> list[dict[str, Any]]:
    out = []
    for i in range(1, len(levels) - 1):
        a, b, c = levels[i - 1], levels[i], levels[i + 1]
        if a is None or b is None or c is None:
            continue
        high = b >= a and b > c
        low = b <= a and b < c
        if not (high or low):
            continue
        curve = a - 2 * b + c
        shift = 0.0 if curve == 0 else max(-0.5, min(0.5, 0.5 * (a - c) / curve))
        peak = b - 0.25 * (a - c) * shift
        when = datetime.fromisoformat(times[i]) + timedelta(minutes=round(shift * 60))
        out.append({"type": "high" if high else "low", "time": when.strftime("%Y-%m-%dT%H:%M"), "height_m": round(peak, 2)})
    return out


def moon(when: datetime) -> dict[str, Any]:
    age = ((when - NEW_MOON).total_seconds() / 86400) % SYNODIC
    lit = round((1 - math.cos(2 * math.pi * age / SYNODIC)) / 2 * 100)
    names = ["New moon (Amavasya)", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon (Purnima)", "Waning gibbous", "Last quarter", "Waning crescent"]
    phase = names[int((age + SYNODIC / 16) / (SYNODIC / 8)) % 8]
    to_spring = min(age % (SYNODIC / 2), SYNODIC / 2 - age % (SYNODIC / 2))
    return {"age_days": round(age, 1), "illumination": lit, "phase": phase, "spring_tide": to_spring <= 2.0}


def windows(hours: list[dict[str, Any]], boat: str) -> list[dict[str, Any]]:
    out, start = [], None
    flags = [h["verdicts"][boat] == "GO" for h in hours] + [False]
    for i, ok in enumerate(flags):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if i - start >= 3:
                end = datetime.fromisoformat(hours[i - 1]["time"]) + timedelta(hours=1)
                out.append({"start": hours[start]["time"], "end": end.strftime("%Y-%m-%dT%H:%M"), "hours": i - start})
            start = None
    return out


async def _fetch(lat: float, lon: float) -> tuple[dict[str, Any], dict[str, Any]]:
    async def load() -> tuple[dict[str, Any], dict[str, Any]]:
        marine, wind = await asyncio.gather(
            get_retry(MARINE, params={"latitude": lat, "longitude": lon, "hourly": MARINE_VARS, "timezone": "auto", "forecast_days": DAYS, "cell_selection": "sea"}, timeout=40),
            get_retry(FORECAST, params={"latitude": lat, "longitude": lon, "hourly": WIND_VARS, "daily": "sunrise,sunset", "current": "temperature_2m", "timezone": "auto", "forecast_days": DAYS}, timeout=40),
        )
        return marine.json(), wind.json()

    return await _cache.get_or_set(coord_key(lat, lon, "sea"), load)


def build(marine: dict[str, Any], wind: dict[str, Any], sea_alerts: list[dict[str, Any]]) -> dict[str, Any]:
    mh = marine.get("hourly") or {}
    if not mh or all(v is None for v in mh.get("wave_height", [None])):
        return {"available": False, "reason": "This place is not on the coast. Pick a coastal town or harbour to see sea conditions."}
    wh = wind["hourly"]
    wind_at = {t: i for i, t in enumerate(wh["time"])}
    now = wind["current"]["time"][:13]
    hours = []
    for i, t in enumerate(mh["time"]):
        if t[:13] < now or t not in wind_at:
            continue
        j = wind_at[t]
        thunder = wh["weather_code"][j] in (95, 96, 99)
        row = {
            "time": t, "wave": mh["wave_height"][i], "wave_dir": compass(mh["wave_direction"][i]), "wave_period": mh["wave_period"][i],
            "wind_wave": mh["wind_wave_height"][i], "swell": mh["swell_wave_height"][i], "swell_dir": compass(mh["swell_wave_direction"][i]), "swell_period": mh["swell_wave_period"][i],
            "current_kmh": mh["ocean_current_velocity"][i], "current_dir": compass(mh["ocean_current_direction"][i]), "sst": mh["sea_surface_temperature"][i], "tide": mh["sea_level_height_msl"][i],
            "wind": wh["wind_speed_10m"][j], "gust": wh["wind_gusts_10m"][j], "wind_dir": compass(wh["wind_direction_10m"][j]), "visibility": wh["visibility"][j],
            "rain": wh["precipitation"][j], "thunder": thunder, "is_day": wh["is_day"][j],
        }
        row["verdicts"] = {}
        row["reasons"] = {}
        for boat in BOATS:
            v, reasons = verdict(boat, row["wave"], row["gust"], thunder, row["visibility"])
            row["verdicts"][boat], row["reasons"][boat] = v, reasons
        hours.append(row)
    if not hours:
        return {"available": False, "reason": "Sea forecast is not available right now."}
    official = bool(sea_alerts)
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for h in hours:
        by_date[h["time"][:10]].append(h)
    sun = {d: (rise, sset) for d, rise, sset in zip(wind["daily"]["time"], wind["daily"]["sunrise"], wind["daily"]["sunset"])}
    all_tides = tides(mh["time"], mh["sea_level_height_msl"])
    days = []
    for date, rows in sorted(by_date.items()):
        if len(rows) < 6 and date != hours[0]["time"][:10]:
            continue
        rank = {"GO": 0, "CAUTION": 1, "NO-GO": 2}
        day_verdicts = {}
        for boat in BOATS:
            daylight = [r for r in rows if r["is_day"]] or rows
            worst = max(daylight, key=lambda r: rank[r["verdicts"][boat]])
            go_hours = sum(1 for r in rows if r["verdicts"][boat] == "GO")
            day_verdicts[boat] = {"verdict": worst["verdicts"][boat], "go_hours": go_hours, "windows": windows(rows, boat)}
        days.append({
            "date": date, "wave_max": max(r["wave"] or 0 for r in rows), "swell_max": max(r["swell"] or 0 for r in rows), "gust_max": round(max(r["gust"] or 0 for r in rows)),
            "wind_max": round(max(r["wind"] or 0 for r in rows)), "rain_mm": round(sum(r["rain"] or 0 for r in rows), 1), "thunder": any(r["thunder"] for r in rows),
            "sunrise": sun.get(date, (None, None))[0], "sunset": sun.get(date, (None, None))[1],
            "tides": [t for t in all_tides if t["time"][:10] == date], "boats": day_verdicts,
        })
    first = hours[0]
    local_now = datetime.fromisoformat(wind["current"]["time"])
    offset = timedelta(seconds=wind.get("utc_offset_seconds") or 0)
    return {
        "available": True, "generated": wind["current"]["time"], "sea_point": {"lat": marine.get("latitude"), "lon": marine.get("longitude")},
        "boats": {k: {"label": v["label"], "caution": v["caution"], "nogo": v["nogo"]} for k, v in BOATS.items()},
        "now": {k: first[k] for k in ("time", "wave", "wave_dir", "wave_period", "wind_wave", "swell", "swell_dir", "swell_period", "current_kmh", "current_dir", "sst", "wind", "gust", "wind_dir", "visibility", "thunder")}
        | {"verdicts": first["verdicts"] if not official else {b: "NO-GO" for b in BOATS}, "reasons": first["reasons"]},
        "official": [{"event": a.get("event"), "severity": a.get("severity"), "headline": a.get("headline"), "expires": a.get("expires"), "issuer": a.get("issuer") or a.get("sender")} for a in sea_alerts[:4]],
        "hours": [{k: h[k] for k in ("time", "wave", "swell", "wind", "gust", "wind_dir", "tide", "thunder", "is_day", "verdicts")} for h in hours[:72]],
        "days": days,
        "next_tides": [t for t in all_tides if t["time"] >= wind["current"]["time"]][:6],
        "moon": moon(local_now.replace(tzinfo=timezone.utc) - offset),
        "rules": "Rule-of-thumb limits by boat type on wave height and wind gusts; thunderstorms and visibility under 1 km add caution. An official fishermen, cyclone or high-wave warning always means do not go.",
        "source": "Open-Meteo marine (wave, swell, currents, sea level) and forecast models; warnings from IMD, INCOIS and state authorities via NDMA SACHET",
    }


async def workspace(lat: float, lon: float, place: dict[str, Any] | None = None) -> dict[str, Any]:
    marine, wind = await _fetch(lat, lon)
    sea_alerts = []
    if place:
        official = alert_service.alerts_for_place(await alert_service.official_alerts(), place)
        sea_alerts = [a for a in official if SEA_WORDS.search(f"{a.get('event')} {a.get('headline')}")]
    return build(marine, wind, sea_alerts)
