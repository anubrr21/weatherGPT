from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.services import advisory
from app.services import alerts as alert_service
from app.services.http import TTLCache, coord_key, get_retry

HOURLY = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,is_day,"
    "soil_temperature_0cm,soil_temperature_6cm,soil_temperature_18cm,soil_moisture_0_to_1cm,soil_moisture_3_to_9cm,soil_moisture_9_to_27cm,soil_moisture_27_to_81cm,"
    "et0_fao_evapotranspiration,vapour_pressure_deficit,sunshine_duration"
)
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,et0_fao_evapotranspiration,sunshine_duration,wind_gusts_10m_max"
PAST_DAYS = 7
AHEAD_DAYS = 7
_cache = TTLCache(ttl_s=1800)

DISEASES: list[dict[str, Any]] = [
    {"id": "rice_blast", "crops": ["paddy"], "name": "Rice blast", "temp": (20, 28), "wet": (8, 12), "source": "IRRI Rice Knowledge Bank",
     "why": "long leaf wetness from dew or drizzle with mild temperatures", "watch": "diamond-shaped grey spots on leaves, rotting at the neck of the panicle"},
    {"id": "rice_sheath_blight", "crops": ["paddy"], "name": "Sheath blight", "temp": (28, 32), "humid": (14, 20), "source": "IRRI Rice Knowledge Bank",
     "why": "hot days with very humid air inside a dense crop", "watch": "oval greenish-grey patches on the leaf sheath near the water line"},
    {"id": "rice_blb", "crops": ["paddy"], "name": "Bacterial leaf blight", "temp": (25, 34), "storm": True, "source": "IRRI Rice Knowledge Bank",
     "why": "warm weather with heavy rain and strong wind that wounds leaves", "watch": "yellow to white drying from the leaf tips and edges"},
    {"id": "wheat_yellow_rust", "crops": ["wheat"], "name": "Yellow (stripe) rust", "temp": (7, 15), "wet": (3, 6), "source": "CIMMYT / ICAR wheat rust guidance",
     "why": "cool nights with dew", "watch": "yellow powdery stripes along the leaf veins"},
    {"id": "wheat_leaf_rust", "crops": ["wheat"], "name": "Brown (leaf) rust", "temp": (15, 25), "wet": (6, 10), "source": "CIMMYT / ICAR wheat rust guidance",
     "why": "mild temperatures with several hours of dew", "watch": "small round orange-brown pustules scattered on leaves"},
    {"id": "late_blight", "crops": ["vegetables"], "name": "Late blight (potato, tomato)", "hutton": True, "source": "Hutton criteria (James Hutton Institute / AHDB)",
     "why": "two days in a row with nights above 10 °C and at least 6 hours of 90% humidity", "watch": "dark water-soaked patches on leaves with white growth underneath"},
    {"id": "chilli_anthracnose", "crops": ["chilli"], "name": "Anthracnose / fruit rot", "temp": (24, 30), "wet": (8, 12), "rain": True, "source": "Published epidemiology ranges",
     "why": "warm, wet weather with rain splash", "watch": "sunken dark spots with rings on ripening fruits"},
    {"id": "groundnut_leaf_spot", "crops": ["groundnut"], "name": "Leaf spot (tikka)", "temp": (20, 28), "wet": (10, 14), "source": "Published epidemiology ranges",
     "why": "long nights of leaf wetness", "watch": "dark round spots with a yellow halo, early leaf fall"},
    {"id": "cotton_leaf_blight", "crops": ["cotton"], "name": "Leaf blight and boll rot", "temp": (25, 32), "wet": (8, 12), "rain": True, "source": "Published epidemiology ranges",
     "why": "warm humid spells with rain", "watch": "brown angular spots on leaves, rotting bolls after rain"},
    {"id": "maize_leaf_blight", "crops": ["maize"], "name": "Turcicum leaf blight", "temp": (18, 27), "wet": (6, 10), "source": "Published epidemiology ranges",
     "why": "moderate temperatures with heavy dew", "watch": "long cigar-shaped grey-green lesions on leaves"},
    {"id": "soybean_rust", "crops": ["soybean"], "name": "Soybean rust", "temp": (18, 28), "wet": (6, 10), "source": "Published epidemiology ranges",
     "why": "mild, wet weather", "watch": "small tan to reddish-brown spots on the underside of leaves"},
    {"id": "pulses_blight", "crops": ["pulses"], "name": "Blight and anthracnose", "temp": (15, 25), "wet": (6, 10), "rain": True, "source": "Published epidemiology ranges",
     "why": "cool, wet spells", "watch": "brown spots with dark margins on leaves, stems and pods"},
    {"id": "mustard_alternaria", "crops": ["mustard"], "name": "Alternaria blight and white rust", "temp": (15, 25), "wet": (6, 10), "source": "Published epidemiology ranges",
     "why": "cool humid weather with dew or fog", "watch": "dark ringed spots on leaves and pods, white pustules under leaves"},
    {"id": "millet_blast", "crops": ["millets"], "name": "Blast", "temp": (24, 30), "wet": (8, 12), "source": "Published epidemiology ranges",
     "why": "warm weather with long leaf wetness", "watch": "spindle-shaped spots on leaves, neck and fingers"},
    {"id": "banana_sigatoka", "crops": ["banana"], "name": "Sigatoka leaf spot", "temp": (23, 28), "wet": (8, 12), "source": "Published epidemiology ranges",
     "why": "warm weather with wet leaves for long hours", "watch": "yellow streaks turning to brown spots with grey centres"},
    {"id": "mango_anthracnose", "crops": ["mango"], "name": "Anthracnose", "temp": (24, 32), "wet": (8, 12), "rain": True, "source": "Published epidemiology ranges",
     "why": "rain and high humidity at flowering and fruiting", "watch": "black spots on leaves, flowers and fruits"},
    {"id": "sugarcane_red_rot", "crops": ["sugarcane"], "name": "Red rot", "temp": (28, 34), "humid": (14, 20), "rain": True, "source": "Published epidemiology ranges",
     "why": "hot, humid weather with waterlogging", "watch": "drying of the top leaves, red patches inside the split cane"},
]
GENERIC = {"id": "fungal", "crops": [], "name": "Fungal leaf diseases", "temp": (18, 30), "wet": (8, 12), "source": "Published epidemiology ranges",
           "why": "warm weather with long leaf wetness", "watch": "new spots on lower leaves after wet nights"}

SOWING: dict[str, tuple[float, float, float]] = {
    "paddy": (18, 25, 35), "wheat": (4, 12, 25), "maize": (10, 18, 32), "cotton": (16, 20, 30), "sugarcane": (18, 26, 33), "groundnut": (18, 22, 32),
    "soybean": (15, 20, 30), "pulses": (8, 15, 30), "mustard": (5, 15, 25), "millets": (15, 25, 35), "vegetables": (10, 18, 30), "chilli": (16, 22, 30),
    "banana": (16, 22, 32), "mango": (16, 22, 32),
}
LEVELS = ["Low", "Moderate", "High"]


def is_wet(h: dict[str, Any]) -> bool:
    temp, dew = h.get("temperature_2m"), h.get("dew_point_2m")
    return (h.get("relative_humidity_2m") or 0) >= 90 or (h.get("precipitation") or 0) > 0.1 or (temp is not None and dew is not None and temp - dew <= 2.0)


def day_stats(hours: list[dict[str, Any]]) -> dict[str, Any]:
    wet = [h for h in hours if is_wet(h)]
    humid = [h for h in hours if (h.get("relative_humidity_2m") or 0) >= 85]
    temps = [h["temperature_2m"] for h in hours if h.get("temperature_2m") is not None]
    wet_temps = [h["temperature_2m"] for h in wet if h.get("temperature_2m") is not None]
    humid_temps = [h["temperature_2m"] for h in humid if h.get("temperature_2m") is not None]
    rh = [h["relative_humidity_2m"] for h in hours if h.get("relative_humidity_2m") is not None]
    return {
        "wet_hours": len(wet), "wet_temp": round(sum(wet_temps) / len(wet_temps), 1) if wet_temps else None,
        "humid_hours": len(humid), "humid_temp": round(sum(humid_temps) / len(humid_temps), 1) if humid_temps else None,
        "rh90_hours": sum(1 for h in hours if (h.get("relative_humidity_2m") or 0) >= 90),
        "tmin": min(temps) if temps else None, "tmax": max(temps) if temps else None, "tmean": round(sum(temps) / len(temps), 1) if temps else None,
        "rh_mean": round(sum(rh) / len(rh)) if rh else None, "rain": round(sum(h.get("precipitation") or 0 for h in hours), 1),
        "gust": max((h.get("wind_gusts_10m") or 0 for h in hours), default=0),
        "sunshine_h": round(sum(h.get("sunshine_duration") or 0 for h in hours) / 3600, 1),
    }


def disease_level(rule: dict[str, Any], today: dict[str, Any], yesterday: dict[str, Any] | None) -> int:
    if rule.get("hutton"):
        def meets(d: dict[str, Any] | None) -> bool:
            return bool(d) and d["tmin"] is not None and d["tmin"] >= 10 and d["rh90_hours"] >= 6
        return 2 if meets(today) and meets(yesterday) else 1 if meets(today) else 0
    low, high = rule["temp"]
    if rule.get("storm"):
        if today["tmean"] is None or not (low <= today["tmean"] <= high):
            return 0
        return 2 if today["rain"] >= 10 and today["gust"] >= 40 else 1 if today["rain"] >= 10 and (today["rh_mean"] or 0) >= 70 else 0
    key, temp_key = ("humid", "humid_temp") if "humid" in rule else ("wet", "wet_temp")
    moderate, severe = rule[key]
    hours, temp = today[f"{key}_hours"], today[temp_key]
    if temp is None or not (low <= temp <= high):
        return 0
    level = 2 if hours >= severe else 1 if hours >= moderate else 0
    if rule.get("rain") and today["rain"] < 1 and level:
        level -= 1
    return level


def disease_outlook(crops: list[str], days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rules = [r for r in DISEASES if any(c in r["crops"] for c in crops)] or [GENERIC]
    out = []
    for rule in rules:
        series = []
        for i, day in enumerate(days):
            level = disease_level(rule, day["stats"], days[i - 1]["stats"] if i else None)
            series.append({"date": day["date"], "level": level, "past": day["past"]})
        ahead = [s for s in series if not s["past"]]
        peak = max((s["level"] for s in ahead), default=0)
        risky = [s["date"] for s in ahead if s["level"] == peak and peak > 0]
        out.append({
            "id": rule["id"], "name": rule["name"], "crops": [c for c in rule["crops"] if c in crops], "peak": peak, "peak_label": LEVELS[peak],
            "risky_days": risky, "days": series, "why": rule["why"], "watch_for": rule["watch"], "source": rule["source"],
        })
    out.sort(key=lambda d: (-d["peak"], -sum(s["level"] for s in d["days"] if not s["past"])))
    return out


BLOCKERS = {
    "rain": "Rain within 6 hours would wash the spray off",
    "wind": "Wind is too strong: the spray would drift",
    "calm": "Air is too still: fine spray hangs and drifts later",
    "heat": "Too hot or too dry: the spray evaporates before it works",
    "dark": "No suitable daylight hours",
}


def tasks_for(day: dict[str, Any], nxt: dict[str, Any] | None, after: dict[str, Any] | None, windows: list[dict[str, Any]], irrigate: bool, deficit: float, blocker: str | None = None) -> list[dict[str, Any]]:
    s = day["stats"]
    rain_48h = s["rain"] + (nxt["stats"]["rain"] if nxt else 0)
    rain_next = (nxt["stats"]["rain"] if nxt else 0) + (after["stats"]["rain"] if after else 0)
    tasks = []
    if windows:
        best = max(windows, key=lambda w: w["hours"])
        tasks.append({"task": "spray", "status": "good", "text": f"Spray {best['start'][11:16]}–{best['end'][11:16]}", "detail": f"{best['hours']} h of light wind and no rain for 6 h after"})
    else:
        tasks.append({"task": "spray", "status": "avoid", "text": "Do not spray", "detail": BLOCKERS.get(blocker or "", "Rain, strong wind or heat would waste the spray")})
    if irrigate:
        tasks.append({"task": "irrigate", "status": "good", "text": "Irrigate", "detail": f"Crop is about {deficit:.0f} mm short and no useful rain is due in 2 days"})
    elif s["rain"] >= 5 or rain_next >= 10:
        tasks.append({"task": "irrigate", "status": "avoid", "text": "Hold irrigation", "detail": "Rain is expected" if s["rain"] < 5 else f"{s['rain']} mm of rain today"})
    if rain_48h >= 20:
        tasks.append({"task": "fertiliser", "status": "avoid", "text": "No fertiliser", "detail": f"{rain_48h:.0f} mm in 48 h would wash it away"})
    elif 2 <= rain_48h < 20 and s["gust"] < 40:
        tasks.append({"task": "fertiliser", "status": "good", "text": "Top-dress fertiliser", "detail": "Light rain will carry it into the soil"})
    dry = s["rain"] < 1 and (day["prob"] or 0) < 40
    if dry and s["sunshine_h"] >= 5 and (s["rh_mean"] or 100) < 80:
        tasks.append({"task": "harvest", "status": "good", "text": "Harvest and dry", "detail": f"{s['sunshine_h']} h of sun, no rain"})
    elif s["rain"] >= 5:
        tasks.append({"task": "harvest", "status": "avoid", "text": "No harvest or drying", "detail": "Rain would wet the produce"})
    if s["rain"] >= 64.5:
        tasks.append({"task": "hazard", "status": "avoid", "text": "Heavy rain", "detail": f"{s['rain']} mm: open field drains, stake tall crops"})
    if s["gust"] >= 50:
        tasks.append({"task": "hazard", "status": "avoid", "text": "Strong wind", "detail": f"Gusts to {s['gust']:.0f} km/h: support bananas and tall crops"})
    if s["tmax"] is not None and s["tmax"] >= 40:
        tasks.append({"task": "hazard", "status": "avoid", "text": "Extreme heat", "detail": f"{s['tmax']:.0f} °C: irrigate in the evening, avoid midday work"})
    if s["tmin"] is not None and s["tmin"] <= 4:
        tasks.append({"task": "hazard", "status": "avoid", "text": "Frost risk", "detail": f"{s['tmin']:.0f} °C at night: light irrigation in the evening protects crops"})
    return tasks


def sowing(crop: str, soil_temp: float | None) -> dict[str, Any] | None:
    if crop not in SOWING or soil_temp is None:
        return None
    low, opt_low, opt_high = SOWING[crop]
    if soil_temp < low:
        verdict, text = "avoid", f"Too cold for seed to sprout (needs at least {low} °C)"
    elif soil_temp < opt_low:
        verdict, text = "caution", f"Seed will sprout slowly (best {opt_low}–{opt_high} °C)"
    elif soil_temp <= opt_high:
        verdict, text = "good", f"Good for sowing (best {opt_low}–{opt_high} °C)"
    else:
        verdict, text = "caution", f"Hot for germination (best {opt_low}–{opt_high} °C); sow with moisture, in the evening"
    return {"crop": crop, "soil_temp": soil_temp, "verdict": verdict, "text": text}


async def _fetch(lat: float, lon: float) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": DAILY, "past_days": PAST_DAYS, "forecast_days": AHEAD_DAYS + 1, "timezone": "auto", "current": "temperature_2m",
        }, timeout=40)
        response.raise_for_status()
        return response.json()

    return await _cache.get_or_set(coord_key(lat, lon, "farm"), load)


def parse_crops(spec: str | None) -> list[tuple[str, str | None]]:
    crops: list[tuple[str, str | None]] = []
    for part in (spec or "").split(","):
        name, _, stage = part.strip().partition(":")
        crop = advisory.normalize_crop(name)
        if crop and crop not in [c for c, _ in crops]:
            crops.append((crop, stage if stage in advisory.STAGES else None))
    return crops[:4]


def build(raw: dict[str, Any], crops: list[tuple[str, str | None]]) -> dict[str, Any]:
    h = raw["hourly"]
    keys = [k for k in h if k != "time"]
    hours = [{"time": t} | {k: h[k][i] for k in keys} for i, t in enumerate(h["time"])]
    now = raw["current"]["time"]
    today = now[:10]
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hour in hours:
        by_date[hour["time"][:10]].append(hour)
    daily = raw["daily"]
    probs = dict(zip(daily["time"], daily["precipitation_probability_max"]))
    et0 = dict(zip(daily["time"], daily["et0_fao_evapotranspiration"]))
    dates = sorted(d for d in by_date if len(by_date[d]) >= 20)
    days = [{"date": d, "past": d < today, "stats": day_stats(by_date[d]), "prob": probs.get(d), "et0": et0.get(d) or 0} for d in dates]
    ahead = [d for d in days if not d["past"]][:AHEAD_DAYS]
    past = [d for d in days if d["past"]]

    future_hours = [x for x in hours if x["time"] >= now[:13]]
    spray = advisory.spray_windows(future_hours)
    windows_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for w in spray["windows"]:
        windows_by_date[w["start"][:10]].append(w)

    primary = crops[0] if crops else (None, None)
    kc = advisory.crop_kc(primary[0], primary[1]) if primary[0] else 1.0
    trigger = 15 if primary[0] == "paddy" else 25
    plan, balance, deficit = [], [], 0.0
    for i, day in enumerate(ahead):
        need = round(day["et0"] * kc, 1)
        rain = day["stats"]["rain"]
        effective = round(min(rain * 0.8, 50), 1) if rain >= 2 else 0.0
        deficit = max(0.0, deficit + need - effective)
        nxt = ahead[i + 1] if i + 1 < len(ahead) else None
        after = ahead[i + 2] if i + 2 < len(ahead) else None
        rain_soon = (nxt["stats"]["rain"] if nxt else 0) + (after["stats"]["rain"] if after else 0)
        irrigate = deficit >= trigger and rain < 5 and rain_soon < 10
        day_hours = [x for x in future_hours if x["time"][:10] == day["date"]]
        blocker = advisory.spray_windows(day_hours)["main_blocker"] if day_hours else None
        tasks = tasks_for(day, nxt, after, windows_by_date.get(day["date"], []), irrigate, deficit, blocker)
        balance.append({"date": day["date"], "need_mm": need, "rain_mm": rain, "effective_mm": effective, "deficit_mm": round(deficit, 1), "irrigate": irrigate})
        if irrigate:
            deficit = 0.0
        s = day["stats"]
        plan.append({
            "date": day["date"], "tmax": s["tmax"], "tmin": s["tmin"], "rain_mm": s["rain"], "rain_prob": day["prob"], "gust": round(s["gust"]), "rh": s["rh_mean"],
            "sunshine_h": s["sunshine_h"], "wet_hours": s["wet_hours"], "tasks": tasks, "spray_windows": windows_by_date.get(day["date"], []),
        })

    soil_now = next((x for x in hours if x["time"] >= now[:13] and x.get("soil_temperature_6cm") is not None), None)
    soil_days = []
    for day in days:
        rows = [x for x in by_date[day["date"]] if x.get("soil_temperature_6cm") is not None]
        if not rows:
            continue
        mean = lambda key: round(sum(r[key] for r in rows) / len(rows), 3)
        soil_days.append({
            "date": day["date"], "past": day["past"], "temp_6cm": round(mean("soil_temperature_6cm"), 1), "temp_18cm": round(mean("soil_temperature_18cm"), 1),
            "moisture_top": mean("soil_moisture_3_to_9cm"), "moisture_root": mean("soil_moisture_9_to_27cm"), "moisture_deep": mean("soil_moisture_27_to_81cm"),
        })
    seed_temp = None
    upcoming = [s["temp_6cm"] for s in soil_days if not s["past"]][:3]
    if upcoming:
        seed_temp = round(sum(upcoming) / len(upcoming), 1)
    crop_names = [c for c, _ in crops]
    livestock = []
    for day in ahead:
        rows = [x for x in by_date[day["date"]] if x.get("temperature_2m") is not None and x.get("relative_humidity_2m") is not None]
        if rows:
            peak = max(advisory.thi(x["temperature_2m"], x["relative_humidity_2m"]) for x in rows)
            livestock.append({"date": day["date"], "thi": peak, "level": "none" if peak < 72 else "mild" if peak < 79 else "moderate" if peak < 89 else "severe"})
    return {
        "generated": now, "timezone": raw.get("timezone"), "today": today,
        "crops": [{"crop": c, "stage": s, "kc": advisory.crop_kc(c, s)} for c, s in crops],
        "plan": plan,
        "spray": {"rules": spray["rules"], "main_blocker": spray["main_blocker"], "count": len(spray["windows"])},
        "water": {
            "crop": primary[0], "stage": primary[1], "kc": kc, "days": balance,
            "need_7d_mm": round(sum(b["need_mm"] for b in balance), 1), "rain_7d_mm": round(sum(b["rain_mm"] for b in balance), 1),
            "effective_7d_mm": round(sum(b["effective_mm"] for b in balance), 1),
            "rain_last_7d_mm": round(sum(d["stats"]["rain"] for d in past), 1), "rainy_days_last_7d": sum(1 for d in past if d["stats"]["rain"] >= 2.5),
            "irrigations": [b["date"] for b in balance if b["irrigate"]],
            "method": f"FAO-56: crop need = reference evaporation × crop factor ({kc}); effective rain = 80% of daily rain of 2 mm or more; irrigate when the running shortfall passes {trigger} mm and no useful rain is due",
        },
        "diseases": disease_outlook(crop_names, days[-(AHEAD_DAYS + 3):] if len(days) > AHEAD_DAYS + 3 else days),
        "soil": {
            "now": soil_now and {
                "temp_surface": soil_now["soil_temperature_0cm"], "temp_6cm": soil_now["soil_temperature_6cm"], "temp_18cm": soil_now["soil_temperature_18cm"],
                "moisture_top": soil_now["soil_moisture_3_to_9cm"], "moisture_root": soil_now["soil_moisture_9_to_27cm"], "moisture_deep": soil_now["soil_moisture_27_to_81cm"],
            },
            "days": soil_days, "seed_depth_temp": seed_temp,
            "sowing": [x for x in (sowing(c, seed_temp) for c in (crop_names or list(SOWING)[:6])) if x],
        },
        "livestock": livestock,
        "note": "Disease risk shows when the weather favours a disease, from published temperature and leaf-wetness ranges. It is not a diagnosis: check the field and ask your Krishi Vigyan Kendra or agriculture officer before spraying.",
        "source": "Open-Meteo best-match forecast and soil model; FAO-56 crop water method",
    }


async def workspace(lat: float, lon: float, crops_spec: str | None, place: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = await _fetch(lat, lon)
    result = build(raw, parse_crops(crops_spec))
    if place:
        official = [a for a in alert_service.alerts_for_place(await alert_service.official_alerts(), place) if a.get("match") == "district"]
        result["warnings"] = [{"event": a.get("event"), "severity": a.get("severity"), "headline": a.get("headline"), "expires": a.get("expires")} for a in official[:5]]
    return result
