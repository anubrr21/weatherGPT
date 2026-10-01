import asyncio
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import advisory, weather
from app.services.cyclones import inside, km
from app.services.http import TTLCache, get_retry
from app.services.trips import airports

DATA = Path(__file__).resolve().parent.parent / "data"
TAF_URL = "https://aviationweather.gov/api/data/taf"
SIGMET_URL = "https://aviationweather.gov/api/data/isigmet"
UA = {"User-Agent": "WeatherGPT/0.1"}
LEVELS = [(925, "FL025"), (850, "FL050"), (700, "FL100"), (500, "FL180"), (400, "FL240"), (300, "FL300"), (250, "FL340"), (200, "FL390")]
CATEGORY_RANK = {"VFR": 0, "MVFR": 1, "IFR": 2, "LIFR": 3}
INDIA_FIRS = ("VABF", "VIDF", "VECF", "VOMF")
HAZARDS = {"TS": "Thunderstorms", "TURB": "Turbulence", "ICE": "Icing", "MTW": "Mountain waves", "VA": "Volcanic ash", "TC": "Tropical cyclone", "DS": "Dust storm", "SS": "Sandstorm"}
_taf_cache = TTLCache(ttl_s=900)
_sigmet_cache = TTLCache(ttl_s=600)
_aloft_cache = TTLCache(ttl_s=1800)


@lru_cache(maxsize=1)
def runways() -> dict[str, Any]:
    path = DATA / "india_runways.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def flight_category(visibility_sm: float | None, ceiling_ft: float | None) -> str:
    vis = 99.0 if visibility_sm is None else visibility_sm
    ceiling = 99999.0 if ceiling_ft is None else ceiling_ft
    if vis < 1 or ceiling < 500:
        return "LIFR"
    if vis < 3 or ceiling < 1000:
        return "IFR"
    if vis <= 5 or ceiling <= 3000:
        return "MVFR"
    return "VFR"


def ceiling_of(clouds: list[dict[str, Any]] | None) -> float | None:
    bases = [c.get("base") for c in clouds or [] if c.get("cover") in ("BKN", "OVC", "OVX") and c.get("base") is not None]
    return min(bases) if bases else None


def visibility_sm(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("+", "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def wind_components(wind_dir: float | None, wind_kt: float | None, heading: float) -> dict[str, float]:
    if wind_dir is None or wind_kt is None:
        return {"headwind": 0.0, "crosswind": 0.0}
    angle = math.radians(wind_dir - heading)
    return {"headwind": round(wind_kt * math.cos(angle), 1), "crosswind": round(abs(wind_kt * math.sin(angle)), 1)}


def runway_winds(icao: str, wind_dir: Any, wind_kt: float | None, gust_kt: float | None) -> list[dict[str, Any]]:
    info = runways().get(icao) or {}
    direction = wind_dir if isinstance(wind_dir, (int, float)) else None
    out = []
    for runway in info.get("runways", []):
        for end in runway["ends"]:
            steady = wind_components(direction, wind_kt, end["heading"])
            gusty = wind_components(direction, gust_kt or wind_kt, end["heading"])
            out.append({
                "runway": end["id"], "heading": end["heading"], "length_ft": runway["length_ft"], "headwind_kt": steady["headwind"], "crosswind_kt": steady["crosswind"],
                "gust_crosswind_kt": gusty["crosswind"], "tailwind": steady["headwind"] < -0.5,
            })
    out.sort(key=lambda r: (-r["headwind_kt"], r["crosswind_kt"]))
    for k, r in enumerate(out):
        r["favoured"] = k == 0 and direction is not None and bool(wind_kt)
    return out


def density_altitude(elevation_ft: float | None, qnh_hpa: float | None, temp_c: float | None) -> dict[str, Any] | None:
    if elevation_ft is None or qnh_hpa is None or temp_c is None:
        return None
    pressure_alt = elevation_ft + (1013.25 - qnh_hpa) * 27
    isa = 15 - 1.98 * pressure_alt / 1000
    density = pressure_alt + 118.8 * (temp_c - isa)
    return {"elevation_ft": round(elevation_ft), "pressure_altitude_ft": round(pressure_alt), "density_altitude_ft": round(density), "isa_deviation_c": round(temp_c - isa, 1)}


def taf_periods(taf: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for f in taf.get("fcsts") or []:
        vis = visibility_sm(f.get("visib"))
        ceiling = ceiling_of(f.get("clouds"))
        wx = f.get("wxString") or ""
        out.append({
            "from": datetime.fromtimestamp(f["timeFrom"], timezone.utc).isoformat(), "to": datetime.fromtimestamp(f["timeTo"], timezone.utc).isoformat(),
            "change": f.get("fcstChange"), "probability": f.get("probability"),
            "wind_dir": f.get("wdir"), "wind_kt": f.get("wspd"), "gust_kt": f.get("wgst"),
            "visibility_km": round(vis * 1.609, 1) if vis is not None else None, "ceiling_ft": ceiling, "weather": wx,
            "clouds": [{"cover": c.get("cover"), "base_ft": c.get("base"), "type": c.get("type")} for c in f.get("clouds") or []],
            "category": flight_category(vis, ceiling), "thunder": "TS" in wx or any(c.get("type") == "CB" for c in f.get("clouds") or []),
        })
    return out


async def taf(icao: str) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        response = await get_retry(TAF_URL, params={"ids": icao, "format": "json"}, headers=UA, timeout=25)
        rows = response.json() if response.content else []
        if not rows:
            return None
        row = rows[0]
        return {"raw": row.get("rawTAF"), "issued": row.get("issueTime"), "periods": taf_periods(row)}

    try:
        return await _taf_cache.get_or_set(icao, load)
    except Exception:
        return None


async def sigmets() -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        response = await get_retry(SIGMET_URL, params={"format": "json"}, headers=UA, timeout=25)
        rows = response.json() if response.content else []
        now = datetime.now(timezone.utc).timestamp()
        out, seen = [], set()
        for r in rows:
            if str(r.get("firId") or "") not in INDIA_FIRS or (r.get("validTimeTo") or 0) < now:
                continue
            key = " ".join((r.get("rawSigmet") or "").split()) or (r.get("firId"), r.get("validTimeFrom"), r.get("hazard"))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "fir": r.get("firId"), "fir_name": (r.get("firName") or "").replace(r.get("firId") or "", "").strip().title(), "hazard": HAZARDS.get(r.get("hazard"), r.get("hazard")),
                "qualifier": r.get("qualifier"), "from": datetime.fromtimestamp(r["validTimeFrom"], timezone.utc).isoformat(), "to": datetime.fromtimestamp(r["validTimeTo"], timezone.utc).isoformat(),
                "top_ft": r.get("top"), "base_ft": r.get("base"), "moving": r.get("dir"), "speed_kt": r.get("spd"), "change": r.get("chng"), "raw": r.get("rawSigmet"),
                "area": [[c["lat"], c["lon"]] for c in r.get("coords") or [] if c.get("lat") is not None],
            })
        return out

    try:
        return await _sigmet_cache.get_or_set("india", load)
    except Exception:
        return []


async def aloft(lat: float, lon: float) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        hourly = ",".join(f"{v}_{p}hPa" for p, _ in LEVELS for v in ("wind_speed", "wind_direction", "temperature", "geopotential_height")) + ",freezing_level_height,cape"
        response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": hourly, "forecast_hours": 25, "timezone": "UTC", "wind_speed_unit": "kn",
        }, timeout=40)
        h = response.json()["hourly"]
        frames = []
        for i in range(0, len(h["time"]), 6):
            levels = []
            for pressure, label in LEVELS:
                height = h[f"geopotential_height_{pressure}hPa"][i]
                levels.append({
                    "level": label, "hpa": pressure, "altitude_ft": round(height * 3.281 / 100) * 100 if height is not None else None,
                    "wind_dir": h[f"wind_direction_{pressure}hPa"][i], "wind_kt": round(h[f"wind_speed_{pressure}hPa"][i]) if h[f"wind_speed_{pressure}hPa"][i] is not None else None,
                    "temp_c": round(h[f"temperature_{pressure}hPa"][i]) if h[f"temperature_{pressure}hPa"][i] is not None else None,
                })
            freezing = h["freezing_level_height"][i]
            frames.append({"time": h["time"][i] + ":00+00:00", "levels": levels, "freezing_level_ft": round(freezing * 3.281 / 100) * 100 if freezing is not None else None, "cape": h["cape"][i]})
        jet = max((lv for f in frames for lv in f["levels"] if lv["wind_kt"] is not None), key=lambda lv: lv["wind_kt"], default=None)
        return {"frames": frames, "strongest": jet, "max_cape": max((f["cape"] or 0 for f in frames), default=0)}

    return await _aloft_cache.get_or_set(f"{lat:.2f},{lon:.2f}", load)


def nearest(lat: float, lon: float, limit: int = 5, max_km: float = 500) -> list[dict[str, Any]]:
    ranked = sorted((a | {"km": round(km((lat, lon), (a["lat"], a["lon"])))} for a in airports()), key=lambda a: a["km"])
    return [a for a in ranked if a["km"] <= max_km][:limit]


async def airport(icao: str) -> dict[str, Any] | None:
    base = next((a for a in airports() if a["icao"] == icao), None)
    if base is None:
        return None
    report, forecast = await asyncio.gather(weather.metar(icao), taf(icao))
    info = runways().get(icao) or {}
    out: dict[str, Any] = {"icao": icao, "iata": base.get("iata"), "name": base["name"], "city": base.get("city"), "lat": base["lat"], "lon": base["lon"], "elevation_ft": info.get("elevation_ft"), "metar": None, "taf": forecast}
    if report.get("available"):
        vis = visibility_sm(report.get("visibility"))
        ceiling = ceiling_of(report.get("clouds"))
        out["metar"] = {
            "raw": report.get("raw_metar"), "observed": report.get("observed"), "decoded": advisory.decode_metar(report.get("raw_metar")),
            "wind_dir": report.get("wind_dir"), "wind_kt": report.get("wind_kt"), "gust_kt": report.get("gust_kt"), "temp_c": report.get("temp_c"), "dewpoint_c": report.get("dewpoint_c"),
            "qnh_hpa": report.get("altimeter_hpa"), "visibility_km": round(vis * 1.609, 1) if vis is not None else None, "ceiling_ft": ceiling,
            "category": report.get("flight_category") or flight_category(vis, ceiling),
        }
        out["runways"] = runway_winds(icao, report.get("wind_dir"), report.get("wind_kt"), report.get("gust_kt"))
        out["density"] = density_altitude(info.get("elevation_ft"), report.get("altimeter_hpa"), report.get("temp_c"))
    return out


def _ceiling_text(ceiling: float | None) -> str:
    return f"ceiling {ceiling:.0f} ft" if ceiling is not None else "no cloud ceiling"


def near_sigmet(sigmet: dict[str, Any], lat: float, lon: float, reach_km: float = 300) -> bool:
    area = sigmet.get("area") or []
    if len(area) >= 3 and inside((lat, lon), [[p[1], p[0]] for p in area]):
        return True
    return any(km((lat, lon), (p[0], p[1])) <= reach_km for p in area)


def hazards(field: dict[str, Any], winds: dict[str, Any], active: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    metar = field.get("metar") or {}
    decoded = metar.get("decoded") or {}
    if "thunderstorm" in decoded.get("hazards", []) or "convective cloud" in decoded.get("hazards", []):
        out.append({"level": "high", "title": "Thunderstorm or cumulonimbus at the field", "detail": "Reported in the latest METAR."})
    periods = (field.get("taf") or {}).get("periods") or []
    stormy = next((p for p in periods if p["thunder"]), None)
    if stormy:
        out.append({"level": "high", "title": "Thunderstorms in the airport forecast", "detail": f"From {stormy['from'][11:16]} UTC ({stormy.get('change') or 'prevailing'})."})
    worst = max(periods, key=lambda p: CATEGORY_RANK[p["category"]], default=None)
    if worst and CATEGORY_RANK[worst["category"]] >= 2:
        out.append({"level": "high" if worst["category"] == "LIFR" else "moderate", "title": f"{worst['category']} conditions forecast", "detail": f"From {worst['from'][11:16]} UTC: visibility {worst['visibility_km']} km, {_ceiling_text(worst['ceiling_ft'])}."})
    if metar.get("category") in ("IFR", "LIFR"):
        out.append({"level": "high", "title": f"{metar['category']} right now", "detail": f"Visibility {metar.get('visibility_km')} km, {_ceiling_text(metar.get('ceiling_ft'))}."})
    best = next((r for r in field.get("runways") or [] if r["favoured"]), None)
    if best and best["gust_crosswind_kt"] >= 15:
        out.append({"level": "high" if best["gust_crosswind_kt"] >= 25 else "moderate", "title": f"Crosswind {best['gust_crosswind_kt']:.0f} kt on runway {best['runway']}", "detail": "Even on the best-aligned runway; check your aircraft's limit."})
    density = field.get("density")
    if density and density["density_altitude_ft"] - density["elevation_ft"] >= 2000:
        out.append({"level": "moderate", "title": f"Density altitude {density['density_altitude_ft']:,} ft", "detail": f"{density['density_altitude_ft'] - density['elevation_ft']:,} ft above field elevation: longer take-off roll, weaker climb."})
    if winds.get("max_cape", 0) >= 1500:
        out.append({"level": "moderate", "title": "Unstable air", "detail": f"CAPE up to {winds['max_cape']:.0f} J/kg in the next 24 h: build-ups and turbulence likely."})
    jet = winds.get("strongest")
    if jet and (jet["wind_kt"] or 0) >= 80:
        out.append({"level": "moderate", "title": f"Jet stream {jet['wind_kt']} kt at {jet['level']}", "detail": "Expect clear-air turbulence near the jet and strong head or tailwinds."})
    for s in active:
        if not s.get("near"):
            continue
        out.append({"level": "high", "title": f"SIGMET: {s['hazard']} in the {s['fir_name'] or s['fir']} FIR", "detail": f"Valid until {s['to'][11:16]} UTC" + (f", tops FL{round(s['top_ft'] / 100)}" if s.get("top_ft") else "") + "."})
    return out


async def workspace(lat: float, lon: float, icao: str | None = None) -> dict[str, Any]:
    near = nearest(lat, lon, limit=14)
    if not near:
        return {"available": False, "reason": "No airport with weather reports within 500 km."}
    fields = [f for f in await asyncio.gather(*(airport(a["icao"]) for a in near)) if f]
    reporting = [f for f in fields if f.get("metar")]
    chosen = icao.upper() if icao and any(a["icao"] == icao.upper() for a in airports()) else None
    field = (await airport(chosen)) if chosen else (reporting[0] if reporting else fields[0])
    home = field["icao"]
    home_info = next(a for a in airports() if a["icao"] == home)
    alternates = [f for f in reporting if f["icao"] != home][:4]
    winds, raw_sigmets = await asyncio.gather(aloft(home_info["lat"], home_info["lon"]), sigmets())
    active = [s | {"near": near_sigmet(s, home_info["lat"], home_info["lon"])} for s in raw_sigmets]
    active.sort(key=lambda s: not s["near"])
    distance = {a["icao"]: a["km"] for a in near}
    return {
        "available": True, "generated": datetime.now(timezone.utc).isoformat(), "airport": field, "distance_km": distance.get(home),
        "alternates": [
            {"icao": a["icao"], "iata": a["iata"], "name": a["name"], "city": a["city"], "km": round(km((home_info["lat"], home_info["lon"]), (a["lat"], a["lon"]))),
             "category": (a.get("metar") or {}).get("category"), "raw": (a.get("metar") or {}).get("raw"), "wind": ((a.get("metar") or {}).get("decoded") or {}).get("wind"),
             "visibility_km": (a.get("metar") or {}).get("visibility_km"), "ceiling_ft": (a.get("metar") or {}).get("ceiling_ft")}
            for a in alternates if a
        ],
        "aloft": winds, "sigmets": active, "hazards": hazards(field or {}, winds, active),
        "choices": [{"icao": f["icao"], "iata": f.get("iata"), "name": f["name"], "km": distance.get(f["icao"]), "reports": bool(f.get("metar"))} for f in fields],
        "source": "METAR, TAF and SIGMET from the Aviation Weather Center (as issued by IMD airport met offices); winds aloft from Open-Meteo pressure levels; runways from OurAirports. For planning support only: always use official briefings.",
    }
