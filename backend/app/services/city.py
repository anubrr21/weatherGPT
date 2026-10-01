import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.services import advisory, weather
from app.services import alerts as alert_service
from app.services.http import TTLCache, coord_key, get_retry

FORECAST = "https://api.open-meteo.com/v1/forecast"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
HOURLY = "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,precipitation_probability,weather_code,wind_speed_10m,wind_gusts_10m,visibility,uv_index,is_day"
PM25_BANDS = [(30, "Good"), (60, "Satisfactory"), (90, "Moderate"), (120, "Poor"), (250, "Very poor"), (10000, "Severe")]
AIR_ADVICE = {
    "Good": "Air is clean. Enjoy outdoor activity.",
    "Satisfactory": "Fine for most people. Very sensitive people may feel minor breathing discomfort.",
    "Moderate": "People with asthma, lung or heart disease, children and older adults should cut down long or heavy exertion outdoors.",
    "Poor": "Most people may feel breathing discomfort on long exposure. Sensitive groups should stay indoors; others should avoid heavy exercise outside.",
    "Very poor": "Respiratory illness is likely on prolonged exposure. Avoid outdoor exercise, wear an N95 mask outside and keep windows closed.",
    "Severe": "Affects healthy people and seriously impacts those with existing disease. Stay indoors, use an N95 mask if you must go out.",
}
_cache = TTLCache(ttl_s=900)


def pm25_band(value: float | None) -> str | None:
    if value is None:
        return None
    return next(label for limit, label in PM25_BANDS if value <= limit)


def flood_level(max_1h: float, max_3h: float, total_24h: float) -> str:
    if max_1h >= 30 or max_3h >= 50 or total_24h >= 115.6:
        return "high"
    if max_1h >= 15 or max_3h >= 30 or total_24h >= 64.5:
        return "moderate"
    if max_1h >= 7.5 or total_24h >= 35:
        return "low"
    return "none"


def commute_block(hours: list[dict[str, Any]], date: str, hour: int, label: str) -> dict[str, Any] | None:
    window = [h for h in hours if h["time"][:10] == date and hour - 1 <= int(h["time"][11:13]) <= hour + 1]
    if not window:
        return None
    wider = [h for h in hours if h["time"][:10] == date and hour - 2 <= int(h["time"][11:13]) <= hour + 2]
    rain = round(sum(h["rain"] for h in window), 1)
    prob = max(h["rain_prob"] for h in window)
    heat = max(h["heat_index"] for h in window)
    thunder = any(h["thunder"] for h in window)
    visibility = min((h["visibility"] for h in window if h["visibility"] is not None), default=None)
    best = min(wider, key=lambda h: (h["rain"] >= 0.5, h["rain_prob"] >= 50, h["rain"], h["rain_prob"], h["heat_index"]))
    tips = []
    if thunder:
        tips.append("Thunderstorm likely: avoid two-wheelers and open stretches")
    if rain >= 7.5:
        tips.append("Heavy rain: expect slow traffic and water on low roads")
    elif rain >= 0.5 or prob >= 50:
        tips.append("Carry an umbrella or raincoat")
    if heat >= 41:
        tips.append("Dangerous heat: carry water, avoid waiting in the sun")
    elif heat >= 35:
        tips.append("Hot and humid: carry water")
    if visibility is not None and visibility < 1000:
        tips.append("Poor visibility: drive slowly with low beam")
    if not tips:
        tips.append("Comfortable commute")
    planned = next((h for h in window if int(h["time"][11:13]) == hour), window[0])
    worth_shifting = best["time"] != planned["time"] and (planned["rain"] - best["rain"] >= 0.5 or planned["rain_prob"] - best["rain_prob"] >= 25)
    return {
        "label": label, "date": date, "hour": hour, "rain_mm": rain, "rain_prob": prob, "heat_index": heat, "thunder": thunder,
        "visibility_km": round(visibility / 1000, 1) if visibility is not None else None, "tips": tips,
        "better_time": best["time"] if worth_shifting else None,
    }


def outdoor_windows(hours: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, start = [], None
    usable = [h for h in hours if 5 <= int(h["time"][11:13]) <= 21]
    flags = []
    for h in usable:
        flags.append(h["rain_prob"] < 30 and h["rain"] < 0.2 and h["heat_index"] < 32 and (h["pm25"] is None or h["pm25"] <= 60) and (h["uv"] or 0) < 8 and not h["thunder"])
    for i, ok in enumerate(flags + [False]):
        same_day = i < len(usable) and start is not None and usable[i]["time"][:10] == usable[start]["time"][:10] and int(usable[i]["time"][11:13]) == int(usable[i - 1]["time"][11:13]) + 1
        if ok and start is None:
            start = i
        elif start is not None and (not ok or not same_day):
            if i - start >= 2:
                block = usable[start:i]
                end = datetime.fromisoformat(block[-1]["time"]) + timedelta(hours=1)
                out.append({"start": block[0]["time"], "end": end.strftime("%Y-%m-%dT%H:%M"), "hours": len(block), "heat_index": max(b["heat_index"] for b in block),
                            "pm25": round(max((b["pm25"] or 0) for b in block))})
            start = i if ok else None
    return out[:6]


async def _fetch(lat: float, lon: float) -> tuple[dict[str, Any], dict[str, Any]]:
    async def load() -> tuple[dict[str, Any], dict[str, Any]]:
        fc, air = await asyncio.gather(
            get_retry(FORECAST, params={"latitude": lat, "longitude": lon, "hourly": HOURLY, "minutely_15": "precipitation", "current": "temperature_2m", "forecast_days": 4, "forecast_minutely_15": 12, "timezone": "auto"}, timeout=40),
            get_retry(AIR, params={"latitude": lat, "longitude": lon, "hourly": "pm2_5,pm10,ozone,nitrogen_dioxide", "forecast_days": 4, "timezone": "auto"}, timeout=40),
        )
        return fc.json(), air.json()

    return await _cache.get_or_set(coord_key(lat, lon, "city"), load)


def build(fc: dict[str, Any], air: dict[str, Any], naqi: dict[str, Any] | None, am: int, pm: int) -> dict[str, Any]:
    h = fc["hourly"]
    air_h = air.get("hourly") or {}
    pm25_at = dict(zip(air_h.get("time") or [], air_h.get("pm2_5") or []))
    pm10_at = dict(zip(air_h.get("time") or [], air_h.get("pm10") or []))
    now = fc["current"]["time"]
    hours = []
    for i, t in enumerate(h["time"]):
        if t[:13] < now[:13]:
            continue
        temp, rh = h["temperature_2m"][i], h["relative_humidity_2m"][i]
        hours.append({
            "time": t, "temp": temp, "rh": rh, "heat_index": advisory.heat_index(temp, rh) if temp is not None and rh is not None else None,
            "rain": h["precipitation"][i] or 0, "rain_prob": h["precipitation_probability"][i] or 0, "thunder": h["weather_code"][i] in (95, 96, 99),
            "wind": h["wind_speed_10m"][i], "gust": h["wind_gusts_10m"][i], "visibility": h["visibility"][i], "uv": h["uv_index"][i], "is_day": h["is_day"][i],
            "pm25": pm25_at.get(t), "pm10": pm10_at.get(t),
        })
    hours = [x for x in hours if x["heat_index"] is not None][:72]
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in hours:
        by_date[x["time"][:10]].append(x)
    dates = sorted(by_date)[:3]

    quarter = fc.get("minutely_15") or {}
    upcoming = [(t, v or 0) for t, v in zip(quarter.get("time") or [], quarter.get("precipitation") or []) if t >= now[:16]]
    first_rain = next((t for t, v in upcoming if v >= 0.1), None)
    minutes = round((datetime.fromisoformat(first_rain) - datetime.fromisoformat(now)).total_seconds() / 60) if first_rain else None

    commutes = [c for date in dates for c in (commute_block(hours, date, am, "Morning"), commute_block(hours, date, pm, "Evening")) if c]
    flooding = []
    for date in dates:
        rows = by_date[date]
        rains = [r["rain"] for r in rows]
        max_1h = max(rains, default=0)
        sums = [sum(rains[i:i + 3]) for i in range(len(rains))]
        max_3h = max(sums, default=0)
        peak = rows[sums.index(max_3h)]["time"] if sums and max_3h > 0 else None
        flooding.append({"date": date, "max_1h_mm": round(max_1h, 1), "max_3h_mm": round(max_3h, 1), "total_mm": round(sum(rains), 1), "level": flood_level(max_1h, max_3h, sum(rains)), "peak_time": peak})

    day_heat = []
    for date in dates:
        rows = by_date[date]
        peak = max(rows, key=lambda r: r["heat_index"])
        risky = [r for r in rows if r["heat_index"] >= 41]
        day_heat.append({
            "date": date, "peak": peak["heat_index"], "peak_time": peak["time"], "band": advisory.heat_band(peak["heat_index"]),
            "danger_from": risky[0]["time"] if risky else None, "danger_to": risky[-1]["time"] if risky else None,
            "uv_max": max((r["uv"] or 0) for r in rows), "tmax": max(r["temp"] for r in rows), "tmin": min(r["temp"] for r in rows),
        })

    air_days = []
    for date in dates:
        values = [r["pm25"] for r in by_date[date] if r["pm25"] is not None]
        if values:
            worst = max(by_date[date], key=lambda r: r["pm25"] or 0)
            cleanest = min((r for r in by_date[date] if r["pm25"] is not None), key=lambda r: r["pm25"])
            air_days.append({"date": date, "pm25_mean": round(sum(values) / len(values)), "pm25_max": round(max(values)), "worst_time": worst["time"], "cleanest_time": cleanest["time"], "band": pm25_band(sum(values) / len(values))})

    current = hours[0]
    band_now = (naqi or {}).get("india_naqi_band") or pm25_band(current["pm25"])
    return {
        "generated": now, "today": now[:10],
        "now": {
            "temp": current["temp"], "heat_index": current["heat_index"], "heat_band": advisory.heat_band(current["heat_index"]), "uv": current["uv"],
            "rain_in_min": minutes, "rain_next_3h_mm": round(sum(v for _, v in upcoming), 1),
            "naqi": (naqi or {}).get("india_naqi"), "air_band": band_now, "dominant": (naqi or {}).get("dominant"), "pm25": current["pm25"], "pm10": current["pm10"],
            "air_advice": AIR_ADVICE.get(band_now or "", None),
        },
        "commute": {"morning_hour": am, "evening_hour": pm, "trips": commutes},
        "flooding": flooding, "heat": day_heat, "air": air_days,
        "outdoor": outdoor_windows(hours[:48]),
        "hours": [{k: x[k] for k in ("time", "heat_index", "rain", "rain_prob", "pm25", "uv", "thunder", "is_day")} for x in hours[:48]],
        "rules": "Waterlogging: heavy bursts of 15 mm in an hour or 30 mm in three hours flood low roads in most Indian cities; 30 mm in an hour or 50 mm in three is high risk. Heat uses the heat index (temperature with humidity). Air bands follow CPCB's PM2.5 breakpoints.",
        "source": "Open-Meteo forecast, 15-minute nowcast and CAMS air-quality forecast; India AQI computed with CPCB breakpoints",
    }


async def workspace(lat: float, lon: float, am: int = 9, pm: int = 18, place: dict[str, Any] | None = None) -> dict[str, Any]:
    (fc, air), naqi = await asyncio.gather(_fetch(lat, lon), weather.air_quality(lat, lon), return_exceptions=False)
    result = build(fc, air, naqi, am, pm)
    if place:
        official = [a for a in alert_service.alerts_for_place(await alert_service.official_alerts(), place) if a.get("match") == "district"]
        result["warnings"] = [{"event": a.get("event"), "severity": a.get("severity"), "headline": a.get("headline"), "expires": a.get("expires")} for a in official[:4]]
    return result
