import re
from datetime import datetime, timedelta
from typing import Any

CROP_KC: dict[str, tuple[float, float, float]] = {
    "paddy": (1.05, 1.20, 0.90),
    "wheat": (0.40, 1.15, 0.40),
    "maize": (0.30, 1.20, 0.60),
    "cotton": (0.35, 1.15, 0.70),
    "sugarcane": (0.40, 1.25, 0.75),
    "groundnut": (0.40, 1.15, 0.60),
    "soybean": (0.40, 1.15, 0.50),
    "pulses": (0.40, 1.00, 0.35),
    "mustard": (0.35, 1.10, 0.35),
    "millets": (0.30, 1.00, 0.30),
    "vegetables": (0.60, 1.15, 0.80),
    "chilli": (0.60, 1.05, 0.90),
    "banana": (0.50, 1.10, 1.00),
    "mango": (0.60, 0.90, 0.75),
}

CROP_ALIASES = {
    "rice": "paddy", "dhan": "paddy", "धान": "paddy", "चावल": "paddy", "వరి": "paddy", "நெல்": "paddy", "ধান": "paddy",
    "गेहूं": "wheat", "गेहूँ": "wheat", "gehu": "wheat",
    "corn": "maize", "मक्का": "maize",
    "कपास": "cotton", "పత్తి": "cotton", "kapas": "cotton",
    "गन्ना": "sugarcane", "ganna": "sugarcane",
    "peanut": "groundnut", "मूंगफली": "groundnut", "వేరుశనగ": "groundnut",
    "soya": "soybean", "सोयाबीन": "soybean",
    "chickpea": "pulses", "gram": "pulses", "lentil": "pulses", "dal": "pulses", "tur": "pulses", "arhar": "pulses", "moong": "pulses", "urad": "pulses", "चना": "pulses", "दाल": "pulses",
    "sarson": "mustard", "सरसों": "mustard",
    "bajra": "millets", "jowar": "millets", "ragi": "millets", "millet": "millets",
    "tomato": "vegetables", "onion": "vegetables", "potato": "vegetables", "brinjal": "vegetables", "vegetable": "vegetables", "सब्जी": "vegetables",
    "chili": "chilli", "mirchi": "chilli", "मिर्च": "chilli", "మిర్చి": "chilli",
}

STAGES = ("initial", "development", "mid", "late")


def normalize_crop(crop: str | None) -> str | None:
    if not crop:
        return None
    key = crop.strip().lower()
    if key in CROP_KC:
        return key
    if key in CROP_ALIASES:
        return CROP_ALIASES[key]
    for alias, name in CROP_ALIASES.items():
        if alias in key:
            return name
    for name in CROP_KC:
        if name in key:
            return name
    return None


def crop_kc(crop: str, stage: str | None) -> float:
    ini, mid, late = CROP_KC[crop]
    return {"initial": ini, "development": round((ini + mid) / 2, 2), "mid": mid, "late": late}.get(stage or "mid", mid)


def _windows(hours: list[dict[str, Any]], ok: list[bool], min_len: int = 2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    start = None
    for i, good in enumerate(ok + [False]):
        if good and start is None:
            start = i
        elif not good and start is not None:
            if i - start >= min_len:
                end = datetime.fromisoformat(hours[i - 1]["time"]) + timedelta(hours=1)
                out.append({"start": hours[start]["time"], "end": end.strftime("%Y-%m-%dT%H:%M"), "hours": i - start})
            start = None
    return out


def spray_windows(hours: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = {"rain": 0, "wind": 0, "calm": 0, "heat": 0, "dark": 0}
    ok = []
    for i, h in enumerate(hours):
        ahead = hours[i:i + 6]
        rain_risk = any((a.get("precipitation_probability") or 0) >= 30 for a in ahead) or sum(a.get("precipitation") or 0 for a in ahead) >= 0.5
        wind = h.get("wind_speed_10m") or 0
        gust = h.get("wind_gusts_10m") or 0
        hot = (h.get("temperature_2m") or 0) > 32 or (h.get("relative_humidity_2m") or 100) < 35
        dark = not h.get("is_day")
        reasons = {"rain": rain_risk, "wind": wind > 15 or gust > 25, "calm": wind < 3, "heat": hot, "dark": dark}
        for k, v in reasons.items():
            if v:
                blockers[k] += 1
        ok.append(not any(reasons.values()))
    main_blocker = max(blockers, key=lambda k: blockers[k] if k != "dark" else -1)
    return {
        "windows": _windows(hours, ok),
        "rules": "Wind 3–15 km/h, gust <25 km/h, no rain ≥30% chance or ≥0.5 mm within 6 h, ≤32 °C, RH ≥35%, daylight",
        "main_blocker": main_blocker if blockers[main_blocker] else None,
    }


def irrigation(daily: list[dict[str, Any]], crop: str | None, stage: str | None) -> dict[str, Any]:
    days = daily[:7]
    kc = crop_kc(crop, stage) if crop else 1.0
    et0 = sum(d.get("et0_fao_evapotranspiration") or 0 for d in days)
    etc = et0 * kc
    rain = sum(d.get("precipitation_sum") or 0 for d in days)
    effective = sum(min((d.get("precipitation_sum") or 0) * 0.8, 50) for d in days if (d.get("precipitation_sum") or 0) >= 2)
    deficit = round(etc - effective, 1)
    if deficit <= 5:
        advice = "Hold irrigation — expected rain covers crop water need this week."
    elif deficit <= 20:
        advice = "Light irrigation needed; schedule after checking soil moisture."
    else:
        advice = "Irrigation needed this week; prefer early morning or evening to cut losses."
    next_rain = next((d["time"] for d in days if (d.get("precipitation_sum") or 0) >= 5), None)
    return {
        "crop": crop,
        "stage": stage,
        "kc": kc,
        "et0_7d_mm": round(et0, 1),
        "crop_water_need_7d_mm": round(etc, 1),
        "rain_7d_mm": round(rain, 1),
        "effective_rain_7d_mm": round(effective, 1),
        "deficit_mm": deficit,
        "next_useful_rain": next_rain,
        "advice": advice + (" Paddy also needs standing water (percolation not included)." if crop == "paddy" else ""),
        "method": "FAO-56 crop coefficient × ET₀, effective rain = 80% of daily rain ≥2 mm",
    }


def dry_spells(daily: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spells = []
    run: list[str] = []
    for d in daily:
        dry = (d.get("precipitation_sum") or 0) < 1 and (d.get("precipitation_probability_max") or 0) < 40
        if dry:
            run.append(d["time"])
        else:
            if len(run) >= 2:
                spells.append({"from": run[0], "to": run[-1], "days": len(run)})
            run = []
    if len(run) >= 2:
        spells.append({"from": run[0], "to": run[-1], "days": len(run)})
    return spells


def thi(temp_c: float, rh: float) -> float:
    return round((1.8 * temp_c + 32) - (0.55 - 0.0055 * rh) * (1.8 * temp_c - 26), 1)


def livestock_stress(hours: list[dict[str, Any]]) -> dict[str, Any]:
    peak = max(hours[:24], key=lambda h: thi(h["temperature_2m"], h["relative_humidity_2m"]))
    value = thi(peak["temperature_2m"], peak["relative_humidity_2m"])
    level = "none" if value < 72 else "mild" if value < 79 else "moderate" if value < 89 else "severe"
    return {"peak_thi": value, "at": peak["time"], "level": level}


def farm_advisory(fc: dict[str, Any], crop: str | None = None, stage: str | None = None) -> dict[str, Any]:
    crop = normalize_crop(crop)
    stage = stage if stage in STAGES else None
    return {
        "spray": spray_windows(fc["hourly"]),
        "irrigation": irrigation(fc["daily"], crop, stage),
        "dry_spells": dry_spells(fc["daily"]),
        "livestock": livestock_stress(fc["hourly"]),
        "heavy_rain_days": [d["time"] for d in fc["daily"][:7] if (d.get("precipitation_sum") or 0) >= 64.5],
    }


def heat_index(temp_c: float, rh: float) -> float:
    t = temp_c * 9 / 5 + 32
    if t < 80:
        hi = 0.5 * (t + 61 + (t - 68) * 1.2 + rh * 0.094)
    else:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
              - 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * ((17 - abs(t - 95)) / 17) ** 0.5
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return round((hi - 32) * 5 / 9, 1)


def heat_band(hi_c: float) -> str:
    if hi_c >= 54:
        return "extreme danger"
    if hi_c >= 41:
        return "danger"
    if hi_c >= 32:
        return "extreme caution"
    if hi_c >= 27:
        return "caution"
    return "comfortable"


def urban_advisory(fc: dict[str, Any]) -> dict[str, Any]:
    hours = fc["hourly"]
    series = [{"time": h["time"], "heat_index": heat_index(h["temperature_2m"], h["relative_humidity_2m"]), "rain": h.get("precipitation") or 0,
               "rain_prob": h.get("precipitation_probability") or 0} for h in hours]
    peak = max(series[:24], key=lambda s: s["heat_index"])
    max_hourly = max((s["rain"] for s in series), default=0)
    max_3h = max((sum(s["rain"] for s in series[i:i + 3]) for i in range(len(series))), default=0)
    if max_hourly >= 20 or max_3h >= 40:
        waterlogging = "high"
    elif max_hourly >= 10 or max_3h >= 20:
        waterlogging = "moderate"
    else:
        waterlogging = "low"
    commutes = []
    for s in series:
        hour = int(s["time"][11:13])
        if hour in (8, 18):
            block = [x for x in series if x["time"][:10] == s["time"][:10] and hour - 1 <= int(x["time"][11:13]) <= hour + 1]
            commutes.append({
                "slot": f"{s['time'][:10]} {'morning' if hour == 8 else 'evening'}",
                "rain_prob": max(b["rain_prob"] for b in block),
                "rain_mm": round(sum(b["rain"] for b in block), 1),
                "heat_index": max(b["heat_index"] for b in block),
            })
    return {
        "heat_index_peak": {**peak, "band": heat_band(peak["heat_index"])},
        "heat_series": [{"time": s["time"], "heat_index": s["heat_index"]} for s in series[:24]],
        "waterlogging_risk": waterlogging,
        "max_hourly_rain_mm": round(max_hourly, 1),
        "max_3h_rain_mm": round(max_3h, 1),
        "commutes": commutes[:4],
    }


def _fishing_verdict(wave: float | None, gust: float | None) -> str:
    wave = wave or 0
    gust = gust or 0
    if wave >= 2.5 or gust >= 50:
        return "NO-GO"
    if wave >= 1.5 or gust >= 35:
        return "CAUTION"
    return "GO"


def fishing_advisory(marine: dict[str, Any], fc: dict[str, Any], official: list[dict[str, Any]]) -> dict[str, Any]:
    sea_alerts = [
        a for a in official
        if re.search(r"fisher|sea|cyclon|depression|squall|coast|wave|tidal", f"{a.get('event')} {a.get('headline')}", re.I)
    ]
    days = []
    marine_daily = {d["time"]: d for d in marine.get("daily", [])} if marine.get("available") else {}
    for d in fc["daily"][:5]:
        m = marine_daily.get(d["time"], {})
        verdict = _fishing_verdict(m.get("wave_height_max"), d.get("wind_gusts_10m_max"))
        days.append({"date": d["time"], "wave_max_m": m.get("wave_height_max"), "gust_max_kmh": d.get("wind_gusts_10m_max"),
                     "rain_mm": d.get("precipitation_sum"), "verdict": verdict})
    if sea_alerts and days:
        days[0]["verdict"] = "NO-GO"
    now_wave = marine.get("current", {}).get("wave_height") if marine.get("available") else None
    now = "NO-GO" if sea_alerts else _fishing_verdict(now_wave, fc["current"].get("wind_gusts_10m"))
    return {
        "available": bool(marine.get("available")),
        "now": now,
        "wave_now_m": now_wave,
        "gust_now_kmh": fc["current"].get("wind_gusts_10m"),
        "days": days,
        "official_sea_alerts": [{"headline": a["headline"], "severity": a["severity"]} for a in sea_alerts[:3]],
        "rules": "NO-GO: waves ≥2.5 m or gusts ≥50 km/h or an official sea/cyclone warning. CAUTION: waves ≥1.5 m or gusts ≥35 km/h.",
    }


WX_CODES = {
    "TS": "thunderstorm", "SH": "showers", "FZ": "freezing", "BL": "blowing", "DR": "drifting", "MI": "shallow", "BC": "patches of",
    "RA": "rain", "DZ": "drizzle", "SN": "snow", "GR": "hail", "GS": "small hail", "BR": "mist", "FG": "fog", "HZ": "haze",
    "DU": "dust", "SA": "sand", "FU": "smoke", "SQ": "squalls", "FC": "funnel cloud", "DS": "duststorm", "SS": "sandstorm", "VC": "in the vicinity",
}
CLOUD_COVER = {"FEW": "few", "SCT": "scattered", "BKN": "broken", "OVC": "overcast"}


def decode_metar(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    tokens = raw.split()
    out: dict[str, Any] = {"weather": [], "clouds": [], "hazards": []}
    for tok in tokens:
        if m := re.fullmatch(r"(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT", tok):
            direction = "variable" if m.group(1) == "VRB" else f"{int(m.group(1))}°"
            out["wind"] = f"{direction} at {int(m.group(2))} kt" + (f", gusting {int(m.group(3))} kt" if m.group(3) else "")
            if m.group(3) and int(m.group(3)) >= 25:
                out["hazards"].append("strong gusts")
        elif re.fullmatch(r"\d{4}", tok) and "visibility" not in out and "wind" in out:
            meters = int(tok)
            out["visibility"] = "10 km or more" if meters == 9999 else f"{meters} m"
            if meters < 1500:
                out["hazards"].append("low visibility")
        elif m := re.fullmatch(r"(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?", tok):
            layer = f"{CLOUD_COVER[m.group(1)]} at {int(m.group(2)) * 100} ft"
            if m.group(3):
                layer += " (cumulonimbus)" if m.group(3) == "CB" else " (towering cumulus)"
                out["hazards"].append("convective cloud")
            out["clouds"].append(layer)
        elif m := re.fullmatch(r"(M?\d{2})/(M?\d{2})", tok):
            out["temp_dew"] = f"{m.group(1).replace('M', '-')} / {m.group(2).replace('M', '-')} °C"
        elif m := re.fullmatch(r"Q(\d{4})", tok):
            out["qnh"] = f"{int(m.group(1))} hPa"
        elif tok in ("NOSIG", "TEMPO", "BECMG"):
            out["trend"] = {"NOSIG": "no significant change expected", "TEMPO": "temporary changes expected", "BECMG": "conditions becoming"}[tok]
            if tok != "NOSIG":
                break
        elif m := re.fullmatch(r"([+-]?)((?:VC|MI|BC|SH|TS|FZ|BL|DR)?(?:RA|DZ|SN|GR|GS|BR|FG|HZ|DU|SA|FU|SQ|FC|DS|SS)+|TS)", tok):
            intensity = {"+": "heavy ", "-": "light "}.get(m.group(1), "")
            words = [WX_CODES[m.group(2)[i:i + 2]] for i in range(0, len(m.group(2)), 2) if m.group(2)[i:i + 2] in WX_CODES]
            out["weather"].append(intensity + " ".join(words))
            if "TS" in tok:
                out["hazards"].append("thunderstorm")
    out["hazards"] = sorted(set(out["hazards"]))
    return out


def home_insights(role: str, fc: dict[str, Any], crop: str | None = None, stage: str | None = None) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    today = fc["daily"][0]
    if role == "farmer":
        farm = farm_advisory(fc, crop, stage)
        w = farm["spray"]["windows"]
        insights.append({
            "kind": "spray",
            "title": "Next spray window",
            "value": f"{_fmt_time(w[0]['start'])}–{w[0]['end'][11:16]}" if w else "None in 48 h",
            "detail": f"{w[0]['hours']} h of calm, dry weather" if w else f"Mostly blocked by {farm['spray']['main_blocker'] or 'weather'}",
            "tone": "calm" if w else "moderate",
        })
        irr = farm["irrigation"]
        insights.append({
            "kind": "irrigation",
            "title": f"Water balance · {irr['crop'] or 'reference crop'}",
            "value": f"{'−' if irr['deficit_mm'] > 0 else '+'}{abs(irr['deficit_mm']):.0f} mm / 7 d",
            "detail": irr["advice"].split(";")[0].split(" — ")[0],
            "tone": "moderate" if irr["deficit_mm"] > 20 else "calm",
        })
        spell = farm["dry_spells"][0] if farm["dry_spells"] else None
        insights.append({
            "kind": "dry",
            "title": "Harvest / drying",
            "value": f"{spell['days']} dry days" if spell else "No dry spell",
            "detail": f"from {_fmt_day(spell['from'])}" if spell else "Rain likely most days — protect produce",
            "tone": "calm" if spell else "moderate",
        })
    elif role == "fisher":
        verdict = _fishing_verdict(None, fc["current"].get("wind_gusts_10m"))
        insights.append({"kind": "sea", "title": "Wind at sea now", "value": f"{fc['current'].get('wind_gusts_10m', 0):.0f} km/h gusts",
                         "detail": "Ask for full sea state and go/no-go", "tone": "calm" if verdict == "GO" else "severe"})
    elif role == "urban":
        urban = urban_advisory(fc)
        peak = urban["heat_index_peak"]
        insights.append({"kind": "heat", "title": "Feels-like peak", "value": f"{peak['heat_index']:.0f} °C at {peak['time'][11:16]}",
                         "detail": peak["band"].capitalize(), "tone": "severe" if peak["heat_index"] >= 41 else "moderate" if peak["heat_index"] >= 32 else "calm"})
        insights.append({"kind": "flood", "title": "Waterlogging risk", "value": urban["waterlogging_risk"].capitalize(),
                         "detail": f"Max {urban['max_3h_rain_mm']} mm in 3 h", "tone": {"high": "severe", "moderate": "moderate"}.get(urban["waterlogging_risk"], "calm")})
        if urban["commutes"]:
            c = urban["commutes"][0]
            insights.append({"kind": "commute", "title": f"Commute · {c['slot'].split()[1]}", "value": f"{c['rain_prob']}% rain",
                             "detail": f"feels {c['heat_index']:.0f} °C", "tone": "moderate" if c["rain_prob"] >= 50 else "calm"})
    if not insights:
        insights.append({"kind": "day", "title": "Today", "value": f"{today['temperature_2m_min']:.0f}–{today['temperature_2m_max']:.0f} °C",
                         "detail": f"{today['condition']['label']}, rain {today['precipitation_sum']:.0f} mm", "tone": "calm"})
        urban = urban_advisory(fc)
        peak = urban["heat_index_peak"]
        insights.append({"kind": "heat", "title": "Feels-like peak", "value": f"{peak['heat_index']:.0f} °C",
                         "detail": f"{peak['band'].capitalize()} at {peak['time'][11:16]}", "tone": "severe" if peak["heat_index"] >= 41 else "calm"})
    return insights


def _fmt_day(iso: str) -> str:
    day = datetime.fromisoformat(iso[:10])
    if day.date() == datetime.now().date():
        return "today"
    return day.strftime("%a %d %b")


def _fmt_time(iso: str) -> str:
    day = datetime.fromisoformat(iso).strftime("%a")
    return f"{day} {iso[11:16]}"
