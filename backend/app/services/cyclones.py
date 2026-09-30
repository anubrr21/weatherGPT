import asyncio
import io
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import alerts as alert_service
from app.services.http import TTLCache, get_retry

log = logging.getLogger("weathergpt.cyclones")

HISTORY = Path(__file__).resolve().parent.parent.parent / "data" / "cyclones" / "ni_storms.json"
GDACS = "https://www.gdacs.org/gdacsapi/api"
JTWC = "https://www.metoc.navy.mil/jtwc/products/abioweb.txt"
RSMC = "https://rsmcnewdelhi.imd.gov.in/"
UA = {"User-Agent": "WeatherGPT/0.1"}
BASIN = {"lat": (-2.0, 32.0), "lon": (40.0, 100.0)}
MS_TO_KT = 1.943844
ONE_TO_THREE_MINUTE = 0.93
RECENT_DAYS = 150
GRADES = [
    (0, "L", "Low pressure area"),
    (17, "D", "Depression"),
    (28, "DD", "Deep Depression"),
    (34, "CS", "Cyclonic Storm"),
    (48, "SCS", "Severe Cyclonic Storm"),
    (64, "VSCS", "Very Severe Cyclonic Storm"),
    (90, "ESCS", "Extremely Severe Cyclonic Storm"),
    (120, "SuCS", "Super Cyclonic Storm"),
]
RADII = {"Poly_Green": 60, "Poly_Orange": 90, "Poly_Red": 120}
STAGES = [
    (12, "post_landfall", "Post-landfall outlook", "Extreme"),
    (24, "warning", "Cyclone warning", "Extreme"),
    (48, "alert", "Cyclone alert", "Severe"),
    (72, "watch", "Pre-cyclone watch", "Moderate"),
]

HELPLINES = [{"number": "1070", "label": "State emergency operations centre"}, {"number": "1077", "label": "District disaster control room"}, {"number": "112", "label": "Emergency response"}]

_live_cache = TTLCache(ttl_s=600)
_outlook_cache = TTLCache(ttl_s=1800)
_local_cache = TTLCache(ttl_s=900)


def grade(kt: float | None) -> dict[str, Any] | None:
    if kt is None:
        return None
    level, code, label = 0, "L", "Low pressure area"
    for n, (floor, c, name) in enumerate(GRADES):
        if kt >= floor:
            level, code, label = n, c, name
    return {"code": code, "label": label, "level": level, "kt": round(kt), "kmh": round(kt * 1.852)}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def bearing_word(origin: tuple[float, float], target: tuple[float, float]) -> str:
    y = math.sin(math.radians(target[1] - origin[1])) * math.cos(math.radians(target[0]))
    x = math.cos(math.radians(origin[0])) * math.sin(math.radians(target[0])) - math.sin(math.radians(origin[0])) * math.cos(math.radians(target[0])) * math.cos(math.radians(target[1] - origin[1]))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][round(deg / 45) % 8]


def inside(point: tuple[float, float], ring: list[list[float]]) -> bool:
    lat, lon = point
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1:
            hit = not hit
    return hit


def _rings(geometry: dict[str, Any]) -> list[list[list[float]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def closest_approach(track: list[dict[str, Any]], place: tuple[float, float]) -> dict[str, Any] | None:
    if not track:
        return None
    scale = math.cos(math.radians(place[0]))
    best: dict[str, Any] | None = None
    pairs = list(zip(track, track[1:])) or [(track[0], track[0])]
    for a, b in pairs:
        ax, ay = (a["lon"] - place[1]) * scale, a["lat"] - place[0]
        bx, by = (b["lon"] - place[1]) * scale, b["lat"] - place[0]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        f = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        lat, lon = a["lat"] + f * (b["lat"] - a["lat"]), a["lon"] + f * (b["lon"] - a["lon"])
        distance = km(place, (lat, lon))
        if best is None or distance < best["km"]:
            ta, tb = datetime.fromisoformat(a["time"]), datetime.fromisoformat(b["time"])
            kts = [k for k in (a.get("kt"), b.get("kt")) if k is not None]
            kt = (a["kt"] + f * (b["kt"] - a["kt"])) if len(kts) == 2 else (kts[0] if kts else None)
            best = {"km": round(distance), "lat": round(lat, 2), "lon": round(lon, 2), "time": (ta + (tb - ta) * f).isoformat(), "kt": kt, "grade": grade(kt), "forecast": bool(b.get("forecast")) if f > 0 else bool(a.get("forecast")), "direction": bearing_word(place, (lat, lon))}
    return best


@lru_cache(maxsize=1)
def history() -> dict[str, Any]:
    if not HISTORY.exists():
        return {"storms": [], "built": None}
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    for storm in data["storms"]:
        lats = [p[1] for p in storm["points"]]
        lons = [p[2] for p in storm["points"]]
        storm["bbox"] = (min(lats), max(lats), min(lons), max(lons))
    return data


def _track_of(storm: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"time": p[0].replace("Z", "+00:00"), "lat": p[1], "lon": p[2], "kt": p[3], "grade_code": p[4], "pressure": p[5], "land": p[6] == 0} for p in storm["points"]]


def storm_detail(sid: str) -> dict[str, Any] | None:
    storm = next((s for s in history()["storms"] if s["sid"] == sid), None)
    if storm is None:
        return None
    return _summary(storm) | {"track": [p | {"grade": grade(p["kt"])} for p in _track_of(storm)]}


def _summary(storm: dict[str, Any]) -> dict[str, Any]:
    return {
        "sid": storm["sid"], "name": storm["name"], "season": storm["season"], "basin": {"BB": "Bay of Bengal", "AS": "Arabian Sea"}.get(storm["basin"] or "", "Land / other"),
        "start": storm["points"][0][0], "end": storm["points"][-1][0], "peak": grade(storm["peak_kt"]), "provisional": storm["provisional"],
        "landfalls": [{"time": t, "lat": la, "lon": lo} for t, la, lo in storm["landfalls"]], "sources": storm["sources"],
    }


def near_history(lat: float, lon: float, radius_km: float = 150, include_tracks: int = 8) -> dict[str, Any]:
    data = history()
    storms = data["storms"]
    if not storms:
        return {"available": False}
    pad_lat = radius_km / 111 + 0.5
    pad_lon = radius_km / (111 * max(0.2, math.cos(math.radians(lat)))) + 0.5
    hits = []
    for storm in storms:
        s, n, w, e = storm["bbox"]
        if lat < s - pad_lat or lat > n + pad_lat or lon < w - pad_lon or lon > e + pad_lon:
            continue
        track = _track_of(storm)
        near = closest_approach(track, (lat, lon))
        if not near or near["km"] > radius_km:
            continue
        landfall = min(((km((lat, lon), (la, lo)), t) for t, la, lo in storm["landfalls"]), default=None)
        hits.append(_summary(storm) | {
            "closest_km": near["km"], "closest_time": near["time"], "at_closest": near["grade"], "direction": near["direction"],
            "landfall_km": round(landfall[0]) if landfall else None,
        })
    first, last = storms[0]["season"], storms[-1]["season"]
    years = last - first + 1
    by_month = [0] * 12
    by_decade: dict[str, int] = {}
    for hit in hits:
        by_month[int(hit["closest_time"][5:7]) - 1] += 1
        decade = f"{hit['season'] // 10 * 10}s"
        by_decade[decade] = by_decade.get(decade, 0) + 1
    storms_cs = [h for h in hits if (h["at_closest"] or {}).get("level", 0) >= 3]
    severe = [h for h in hits if (h["peak"] or {}).get("level", 0) >= 4]
    landfalls_near = [h for h in hits if h["landfall_km"] is not None and h["landfall_km"] <= radius_km]
    hits.sort(key=lambda h: h["closest_time"], reverse=True)
    strongest = sorted(hits, key=lambda h: ((h["at_closest"] or {}).get("kt") or 0), reverse=True)[:5]
    tracks = {h["sid"] for h in (strongest + hits[:include_tracks])}
    track_lines = {s["sid"]: [[p[1], p[2], p[3]] for p in s["points"]] for s in storms if s["sid"] in tracks}
    return {
        "available": True, "radius_km": radius_km, "since": first, "until": last, "built": data.get("built"),
        "count": len(hits), "cyclonic_storms": len(storms_cs), "severe_or_worse": len(severe), "landfalls": len(landfalls_near),
        "return_period_years": round(years / len(storms_cs), 1) if storms_cs else None,
        "by_month": by_month, "by_decade": dict(sorted(by_decade.items())),
        "storms": hits[:60],
        "strongest": [h["sid"] for h in strongest],
        "tracks": track_lines,
        "source": "IBTrACS v04r01 North Indian Ocean best tracks (IMD RSMC New Delhi, WMO and JTWC)",
    }


@lru_cache(maxsize=1)
def climatology() -> dict[str, Any]:
    storms = history()["storms"]
    months = {"Bay of Bengal": [0] * 12, "Arabian Sea": [0] * 12}
    for storm in storms:
        if storm["peak_kt"] < 34 or storm["basin"] not in ("BB", "AS"):
            continue
        first_cs = next((p for p in storm["points"] if p[3] and p[3] >= 34), storm["points"][0])
        months["Bay of Bengal" if storm["basin"] == "BB" else "Arabian Sea"][int(first_cs[0][5:7]) - 1] += 1
    seasons = (storms[-1]["season"] - storms[0]["season"] + 1) if storms else 1
    return {"per_month": months, "seasons": seasons, "since": storms[0]["season"] if storms else None, "note": "Cyclonic storms (34 kt or more) by the month they first reached that strength"}


def in_basin(lat: float, lon: float) -> bool:
    return BASIN["lat"][0] <= lat <= BASIN["lat"][1] and BASIN["lon"][0] <= lon <= BASIN["lon"][1]


def _time(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%d %b %Y %H:%M").replace(tzinfo=timezone.utc)


def _num(value: Any) -> float | None:
    try:
        number = float(str(value).strip().rstrip(">"))
    except ValueError:
        return None
    return number


async def _json(url: str, **params: Any) -> Any:
    response = await get_retry(url, params=params or None, headers=UA, timeout=30)
    response.raise_for_status()
    return response.json()


def _gdacs_fixes(timeline: list[dict[str, Any]], geometry: dict[str, Any]) -> tuple[list[dict[str, Any]], datetime | None]:
    observed = []
    for item in sorted((i for i in timeline if i.get("actual") == "True"), key=lambda i: int(i["advisory_number"])):
        wind_ms = _num(item.get("wind_speed"))
        kt = wind_ms * MS_TO_KT * ONE_TO_THREE_MINUTE if wind_ms is not None else None
        gust_ms = _num(item.get("wind_gusts"))
        radii = {q: _num(item.get(f"windrad_nm_34kt_{q}")) for q in ("ne", "se", "sw", "nw")}
        observed.append({
            "time": _time(item["advisory_datetime"]).isoformat(), "lat": float(item["latitude"]), "lon": float(item["longitude"]), "kt": kt,
            "gust_kmh": round(gust_ms * 3.6) if gust_ms else None, "pressure": _num(item.get("pressure")) or None,
            "status": (item.get("storm_status") or [None])[0], "forecast": False, "advisory": int(item["advisory_number"]),
            "gale_radius_km": {q: round(v * 1.852) for q, v in radii.items() if v}, "population_gale": int(_num(item.get("pop39")) or 0),
        })
    if not observed:
        return [], None
    issued = datetime.fromisoformat(observed[-1]["time"])
    stamps = set()
    for feature in geometry.get("features", []):
        key = feature["properties"].get("key")
        if feature["properties"].get("featuretype") in ("PointRadii", "WindRadii") and key and len(key) == 8:
            year = issued.year + (1 if issued.month == 12 and key.startswith("01") else 0)
            stamps.add(datetime.strptime(f"{year}{key}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc))
    future = sorted(t for t in stamps if t > issued)
    latest = max(int(i["advisory_number"]) for i in timeline)
    forecast_items = [i for i in timeline if i.get("actual") == "False" and int(i["advisory_number"]) == latest]
    forecast = []
    for n, item in enumerate(forecast_items):
        when = future[n] if n < len(future) else issued + timedelta(hours=12 * (n + 1))
        wind_ms = _num(item.get("wind_speed"))
        forecast.append({
            "time": when.isoformat(), "lat": float(item["latitude"]), "lon": float(item["longitude"]),
            "kt": wind_ms * MS_TO_KT * ONE_TO_THREE_MINUTE if wind_ms is not None else None, "status": (item.get("storm_status") or [None])[0], "forecast": True,
        })
    return observed + forecast, issued


def _gdacs_shapes(geometry: dict[str, Any]) -> dict[str, Any]:
    cone, swath, radii = None, None, []
    for feature in geometry.get("features", []):
        props = feature["properties"]
        if props.get("polygonlabel") == "Uncertainty Cones":
            cone = feature["geometry"]
        elif props.get("featuretype") == "WindRadii" and props.get("Class") in RADII:
            radii.append({"time": datetime.strptime(props["polygondate"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).isoformat(), "kmh": RADII[props["Class"]], "geometry": feature["geometry"]})
        elif props.get("Class") == "Poly_Green" and props.get("polygonlabel", "").endswith("km/h") and not props.get("featuretype"):
            swath = feature["geometry"]
    return {"cone": cone, "swath": swath, "radii": radii}


async def _gdacs_storm(event: dict[str, Any]) -> dict[str, Any] | None:
    props = event["properties"]
    try:
        details, geometry = await asyncio.gather(
            _json(f"{GDACS}/events/geteventdata", eventtype="TC", eventid=props["eventid"]),
            _json(f"{GDACS}/polygons/getgeometry", eventtype="TC", eventid=props["eventid"], episodeid=props["episodeid"]),
        )
        timeline_url = next((i["resource"]["timeline"] for i in details["properties"].get("impacts") or [] if i.get("resource", {}).get("timeline")), None)
        timeline = (await _json(timeline_url))["channel"]["item"] if timeline_url else []
    except Exception as exc:
        log.info("GDACS storm %s unavailable: %s", props.get("eventname"), exc)
        return None
    if isinstance(timeline, dict):
        timeline = [timeline]
    track, issued = _gdacs_fixes(timeline, geometry)
    if not track:
        return None
    surge = None
    for block in details["properties"].get("cyclonesurge") or []:
        latest = next((d for d in block.get("data") or [] if d.get("last")), None)
        if latest:
            try:
                info = (await _json(latest["url"]))["properties"]
                surge = {"max_m": round(info.get("maxheight") or 0, 2), "max_rain_mm": info.get("maxrain"), "max_wind_ms": info.get("maxwind"), "source": block.get("source"), "issued": info.get("episodedate")}
            except Exception:
                pass
    observed = [p for p in track if not p["forecast"]]
    peak = max((p["kt"] for p in observed if p["kt"] is not None), default=None)
    images = details["properties"].get("images") or {}
    return {
        "id": f"gdacs-{props['eventid']}", "name": props.get("eventname"), "source": props.get("source") or "JTWC", "alert_level": props.get("alertlevel"),
        "current": str(props.get("iscurrent")).lower() == "true", "countries": [c["countryname"] for c in props.get("affectedcountries") or []],
        "start": props.get("fromdate"), "end": props.get("todate"), "issued": issued.isoformat() if issued else None,
        "now": observed[-1] | {"grade": grade(observed[-1]["kt"])}, "peak": grade(peak),
        "track": [p | {"grade": grade(p["kt"])} for p in track], "shapes": _gdacs_shapes(geometry), "surge": surge,
        "images": {k: images[k] for k in ("rainaccumulationmap", "rainmap", "overviewmap") if images.get(k)},
        "report": (props.get("url") or {}).get("report"),
    }


async def _jtwc_outlook() -> dict[str, Any]:
    try:
        text = (await get_retry(JTWC, headers=UA, timeout=25)).text
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    block = text.split("2. SOUTH INDIAN OCEAN")[0]
    sections = {}
    for key, label in (("A", "cyclones"), ("B", "disturbances"), ("C", "subtropical")):
        found = re.search(rf"{key}\.\s+[A-Z /]+SUMMARY:\s*(.*?)(?=\n\s+[A-C]\.\s|\Z)", block, re.S)
        sections[label] = re.sub(r"\s+", " ", found.group(1)).strip().rstrip("/") if found else None
    valid = re.search(r"/(\d{6}Z(?:[A-Z]{3}\d{4})?-\s*(\d{2})(\d{2})(\d{2})Z([A-Z]{3})(\d{4}))", re.sub(r"\s+", "", text))
    until = None
    if valid:
        try:
            until = datetime.strptime(f"{valid.group(2)} {valid.group(5)} {valid.group(6)} {valid.group(3)}:{valid.group(4)}", "%d %b %Y %H:%M").replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            until = None
    quiet = all((v or "NONE.").upper().startswith("NONE") for v in sections.values())
    return {"available": True, "issuer": "Joint Typhoon Warning Center", "valid": valid.group(1) if valid else None, "valid_until": until, "sections": sections, "quiet": quiet, "url": JTWC}


async def _imd_bulletins() -> dict[str, Any]:
    from pypdf import PdfReader

    try:
        html = (await get_retry(RSMC + "rsmc-tropical-cyclones.php", headers=UA, timeout=25)).text
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    links = {re.sub(r"<[^>]+>", "", label).strip().lower(): href for href, label in re.findall(r'<a[^>]+href="(download\.php\?path=[^"]+)"[^>]*>(.*?)</a>', html, re.S)}
    out: dict[str, Any] = {"available": True, "page": RSMC + "rsmc-tropical-cyclones.php"}
    for kind in ("special", "routine"):
        href = links.get(kind)
        if not href:
            continue
        url = RSMC + href
        try:
            data = (await get_retry(url, headers=UA, timeout=40)).content
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages[:3]) if data[:4] == b"%PDF" else ""
        except Exception as exc:
            out[kind] = {"url": url, "error": str(exc)}
            continue
        text = re.sub(r"[ \t]+", " ", text).replace("�", "°").strip()
        stamp = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})\s*Time:\s*(\d{2}:\d{2})", text)
        issued = f"{stamp.group(1)}T{stamp.group(2)}:00+00:00" if stamp else None
        out[kind] = {"url": url, "nil": text.upper().strip(" .") in ("NIL", ""), "issued": issued, "text": text[:2400]}
    return out


async def outlook() -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        jtwc, imd = await asyncio.gather(_jtwc_outlook(), _imd_bulletins())
        return {"jtwc": jtwc, "imd": imd}

    return await _outlook_cache.get_or_set("outlook", load)


async def storms() -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        listing = await _json(f"{GDACS}/events/geteventlist/SEARCH", eventlist="TC", fromdate=(now - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d"), todate=(now + timedelta(days=1)).strftime("%Y-%m-%d"))
        events = [e for e in listing.get("features", []) if in_basin(e["geometry"]["coordinates"][1], e["geometry"]["coordinates"][0]) or "India" in (e["properties"].get("country") or "")]
        loaded = [s for s in await asyncio.gather(*(_gdacs_storm(e) for e in events)) if s]
        loaded.sort(key=lambda s: (not s["current"], s["start"] or ""), reverse=False)
        return {"fetched": now.isoformat(), "active": [s for s in loaded if s["current"]], "recent": sorted([s for s in loaded if not s["current"]], key=lambda s: s["start"] or "", reverse=True)}

    return await _live_cache.get_or_set("storms", load)


def stage_for(hours: float, near_km: float, in_cone: bool) -> dict[str, Any] | None:
    if hours < -6 or not (in_cone or near_km <= 250):
        return None
    for limit, code, label, severity in STAGES:
        if hours <= limit:
            return {"code": code, "label": label, "severity": severity, "lead_hours": round(hours)}
    return None


def impact(storm: dict[str, Any], lat: float, lon: float) -> dict[str, Any]:
    place = (lat, lon)
    near = closest_approach(storm["track"], place)
    now = datetime.now(timezone.utc)
    shapes = storm["shapes"]
    cone = bool(shapes.get("cone")) and any(inside(place, ring) for ring in _rings(shapes["cone"]))
    winds = []
    for radius in shapes.get("radii") or []:
        if any(inside(place, ring) for ring in _rings(radius["geometry"])):
            winds.append({"kmh": radius["kmh"], "time": radius["time"]})
    strongest = max(winds, key=lambda w: w["kmh"]) if winds else None
    first_gale = min((w["time"] for w in winds), default=None)
    hours = (datetime.fromisoformat(near["time"]) - now).total_seconds() / 3600 if near else None
    current = storm["now"]
    distance_now = round(km(place, (current["lat"], current["lon"])))
    return {
        "distance_now_km": distance_now, "direction_now": bearing_word(place, (current["lat"], current["lon"])),
        "closest": near, "hours_to_closest": round(hours, 1) if hours is not None else None,
        "in_cone": cone, "wind_zone": strongest, "first_gale": first_gale,
        "stage": stage_for(hours, near["km"], cone) if near and hours is not None and storm["current"] else None,
    }


async def local_forecast(lat: float, lon: float) -> dict[str, Any]:
    key = f"{lat:.2f},{lon:.2f}"

    async def load() -> dict[str, Any]:
        response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": "wind_speed_10m,wind_gusts_10m,precipitation,pressure_msl", "forecast_days": 4, "timezone": "UTC", "wind_speed_unit": "kmh",
        }, timeout=25)
        hourly = response.json()["hourly"]
        rows = [
            {"time": t + "+00:00", "wind": w, "gust": g, "rain": r, "pressure": p}
            for t, w, g, r, p in zip(hourly["time"], hourly["wind_speed_10m"], hourly["wind_gusts_10m"], hourly["precipitation"], hourly["pressure_msl"])
        ]
        upcoming = [r for r in rows if datetime.fromisoformat(r["time"]) >= datetime.now(timezone.utc) - timedelta(hours=1)][:84]
        peak = max(upcoming, key=lambda r: r["gust"] or 0) if upcoming else None
        low = min(upcoming, key=lambda r: r["pressure"] or 9999) if upcoming else None
        return {
            "hours": upcoming[::3], "max_gust": peak and {"kmh": round(peak["gust"] or 0), "time": peak["time"]},
            "rain_72h_mm": round(sum(r["rain"] or 0 for r in upcoming[:72]), 1), "min_pressure": low and {"hpa": round(low["pressure"] or 0), "time": low["time"]},
            "source": "Open-Meteo best-match forecast (ECMWF, GFS, ICON and regional models)",
        }

    return await _local_cache.get_or_set(key, load)


def _is_cyclone_alert(alert: dict[str, Any]) -> bool:
    text = " ".join(str(alert.get(k) or "") for k in ("event", "headline", "instruction")).lower()
    return any(word in text for word in ("cyclon", "depression", "storm surge", "tidal wave", "low pressure"))


SHELTER_KINDS = {"cyclone": "Cyclone shelter", "relief": "Relief shelter", "assembly": "Assembly point", "public": "Public building"}


@lru_cache(maxsize=1)
def _shelter_index() -> dict[tuple[int, int], list[dict[str, Any]]]:
    path = HISTORY.parent / "shelters.json"
    index: dict[tuple[int, int], list[dict[str, Any]]] = {}
    if not path.exists():
        return index
    for item in json.loads(path.read_text(encoding="utf-8"))["shelters"]:
        index.setdefault((int(item["lat"] // 0.25), int(item["lon"] // 0.25)), []).append(item)
    return index


def shelters(lat: float, lon: float, radius_km: int = 30) -> dict[str, Any]:
    index = _shelter_index()
    reach = int(radius_km / 27) + 1
    cell = (int(lat // 0.25), int(lon // 0.25))
    found = []
    for dlat in range(-reach, reach + 1):
        for dlon in range(-reach, reach + 1):
            for item in index.get((cell[0] + dlat, cell[1] + dlon), []):
                distance = km((lat, lon), (item["lat"], item["lon"]))
                if distance <= radius_km:
                    found.append({"name": None} | item | {"km": round(distance, 1), "label": SHELTER_KINDS[item["kind"]] if item["kind"] != "public" else item.get("type") or "Public building"})
    designated = sorted((f for f in found if f["kind"] != "public"), key=lambda f: f["km"])[:15]
    public = sorted((f for f in found if f["kind"] == "public"), key=lambda f: f["km"])[:15]
    return {
        "radius_km": radius_km, "designated": designated, "public": public, "indexed": bool(index),
        "note": "Designated shelters are the ones mapped in OpenStreetMap, which misses many. Government schools and community halls are commonly opened as relief camps by the district administration; confirm which one is open with the district control room.",
        "source": "OpenStreetMap contributors (Geofabrik India extract)", "helplines": HELPLINES,
    }


async def live(lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    data, look = await asyncio.gather(storms(), outlook())
    result: dict[str, Any] = {"fetched": data["fetched"], "outlook": look, "active": [], "recent": [], "season": [], "climatology": climatology()}
    for storm in data["active"]:
        result["active"].append(storm | ({"impact": impact(storm, lat, lon)} if lat is not None else {}))
    for storm in data["recent"][:12]:
        result["recent"].append(storm | ({"impact": impact(storm, lat, lon)} if lat is not None else {}))
    this_year = datetime.now(timezone.utc).year
    result["season"] = [_summary(s) for s in history()["storms"] if s["season"] == this_year]
    if lat is not None:
        official = await alert_service.official_alerts()
        place = {"lat": lat, "lon": lon}
        try:
            from app.services import weather

            place = await weather.reverse_geocode(lat, lon) | place
        except Exception:
            pass
        result["official"] = [a for a in alert_service.alerts_for_place(official, place) if _is_cyclone_alert(a)]
        result["nearest_landfall_km"] = nearest_landfall(lat, lon)
    return result


def nearest_landfall(lat: float, lon: float) -> float | None:
    best = None
    for storm in history()["storms"]:
        for t, la, lo in storm["landfalls"]:
            d = km((lat, lon), (la, lo))
            if best is None or d < best:
                best = d
    return round(best) if best is not None else None


async def status_for_agent(lat: float, lon: float, name: str) -> dict[str, Any]:
    data = await live(lat, lon)
    past = near_history(lat, lon, 150, include_tracks=0)
    active = [{
        "name": s["name"], "now": {"grade": s["now"]["grade"], "lat": s["now"]["lat"], "lon": s["now"]["lon"], "time": s["now"]["time"]},
        "impact": s.get("impact"), "surge": s.get("surge"), "issued": s["issued"], "source": s["source"],
    } for s in data["active"]]
    return {
        "place": name, "active_storms": active, "jtwc_outlook": data["outlook"]["jtwc"].get("sections"),
        "imd_special_bulletin": {k: v for k, v in (data["outlook"]["imd"].get("special") or {}).items() if k != "url"} or None,
        "official_cyclone_warnings": [{"event": a.get("event"), "severity": a.get("severity"), "headline": a.get("headline")} for a in data.get("official", [])],
        "recent_storms": [{"name": s["name"], "start": s["start"], "peak": s["peak"], "closest_km": (s.get("impact") or {}).get("closest", {}).get("km") if s.get("impact") and s["impact"].get("closest") else None} for s in data["recent"][:5]],
        "history_within_150km_since_1980": {k: past.get(k) for k in ("count", "cyclonic_storms", "severe_or_worse", "landfalls", "return_period_years", "by_month")} | {
            "most_recent": [{"name": s["name"], "season": s["season"], "closest_km": s["closest_km"], "at_closest": (s["at_closest"] or {}).get("label")} for s in past.get("storms", [])[:5]],
            "strongest_here": [{"name": s["name"], "season": s["season"], "closest_km": s["closest_km"], "at_closest": (s["at_closest"] or {}).get("label"), "peak": (s["peak"] or {}).get("label"), "landfall_km": s["landfall_km"]} for sid in past.get("strongest", []) for s in past.get("storms", []) if s["sid"] == sid],
        },
        "imd_grades": "D 17-27 kt, DD 28-33, CS 34-47, SCS 48-63, VSCS 64-89, ESCS 90-119, SuCS 120+ (3-minute winds)",
    }


def _ist(value: str) -> str:
    return (datetime.fromisoformat(value) + timedelta(hours=5, minutes=30)).strftime("%a %d %b, %H:%M IST")


def warning_text(storm: dict[str, Any], hit: dict[str, Any], place: str) -> tuple[str, str]:
    now = storm["now"]
    g = now.get("grade") or {"label": "Cyclonic disturbance", "kmh": None}
    name = storm["name"] or "The cyclonic system"
    stage = hit["stage"]
    title = f"{stage['label']}: {g['label']} {name} — {place}"
    parts = [f"{name} is {hit['distance_now_km']} km {hit['direction_now']} of {place} as a {g['label'].lower()}" + (f" with winds near {g['kmh']} km/h." if g.get("kmh") else ".")]
    closest = hit.get("closest")
    if closest:
        parts.append(f"It is forecast to pass about {closest['km']} km from {place} around {_ist(closest['time'])}" + (", and your place is inside the forecast cone." if hit["in_cone"] else "."))
    if hit.get("wind_zone"):
        parts.append(f"Winds of {hit['wind_zone']['kmh']} km/h or more are expected here from about {_ist(hit['first_gale'])}.")
    if storm.get("surge") and storm["surge"].get("max_m", 0) >= 1:
        parts.append(f"Storm surge up to {storm['surge']['max_m']} m is modelled along the coast; stay away from the sea front.")
    parts.append("Follow IMD and district instructions, keep documents, water, medicines and a charged phone ready, and know your nearest cyclone shelter.")
    return title, " ".join(parts)


async def notify() -> dict[str, int]:
    from sqlalchemy import select

    from app.db import PhoneSubscriber, Session
    from app.services import phone, smart

    data = await storms()
    if not data["active"]:
        return {"notices": 0, "pushed": 0, "sms": 0, "calls": 0}
    places = await smart._places()
    prefs = await smart._prefs(sorted({c for p in places.values() for c in p["clients"]})) if places else {}
    created = []
    for storm in data["active"]:
        for place in places.values():
            hit = impact(storm, place["lat"], place["lon"])
            if not hit["stage"]:
                continue
            title_en, body_en = warning_text(storm, hit, place["name"])
            for client in place["clients"]:
                language = prefs[client].language if client in prefs else "en"
                title, body = (title_en, body_en) if language == "en" else (await phone.say(title_en, language), await phone.say(body_en, language))
                notice = await smart._store(
                    client, "cyclone", hit["stage"]["severity"], title, body, place,
                    {"storm": storm["id"], "name": storm["name"], "stage": hit["stage"]["code"], "closest_km": (hit.get("closest") or {}).get("km"), "issued": storm["issued"]},
                    f"cyclone:{storm['id']}:{hit['stage']['code']}",
                )
                if notice:
                    created.append(notice)
    delivered = await smart.deliver(created)
    async with Session() as s:
        subs = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.active.is_(True), PhoneSubscriber.confirmed.is_(True), PhoneSubscriber.lat.is_not(None)))).all()
    sms = calls = 0
    for storm in data["active"]:
        for sub in subs:
            hit = impact(storm, sub.lat, sub.lon)
            if not hit["stage"]:
                continue
            _, body = warning_text(storm, hit, sub.place_name or "your area")
            text = await phone.say(f"WeatherGPT {hit['stage']['label']}: {body}", sub.language)
            key = f"cyclone:{storm['id']}:{hit['stage']['code']}"
            if sub.sms and await phone.send_sms(sub.phone, text, kind="warning", dedup=key, max_segments=4):
                sms += 1
            if sub.voice and hit["stage"]["code"] in ("alert", "warning", "post_landfall"):
                if await phone.place_call(sub.phone, "warning", {"summary": text, "severity": hit["stage"]["severity"], "storm": storm["id"]}, dedup=f"call:{key}"):
                    calls += 1
    return {"notices": delivered["created"], "pushed": delivered["pushed"], "sms": sms, "calls": calls}
