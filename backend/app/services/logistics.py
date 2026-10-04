import asyncio
import hashlib
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services import cyclones, fieldmap, providers, trips, weather
from app.services.http import TTLCache, client
from app.services.trips import Route, TripError, bearing, cumulative, haversine
from app.services.wmo import describe

log = logging.getLogger("weathergpt.logistics")

IST = timezone(timedelta(hours=5, minutes=30))
LAND_HOURLY = "temperature_2m,apparent_temperature,dew_point_2m,relative_humidity_2m,precipitation,weather_code,wind_gusts_10m,wind_direction_10m,visibility,is_day"
AIR_HOURLY = LAND_HOURLY + ",cape,wind_speed_250hPa,wind_direction_250hPa"
LANE_HOURLY = "temperature_2m,apparent_temperature,precipitation,weather_code,wind_gusts_10m,wind_direction_10m,visibility,is_day"
MARINE_HOURLY = "wave_height,wave_direction,wave_period,swell_wave_height"
SITE_HOURLY = "temperature_2m,apparent_temperature,precipitation,weather_code,wind_gusts_10m,visibility"
LANE_CACHE = Path(__file__).resolve().parent.parent.parent / "data" / "logistics" / "lanes.json"
LEVELS = ["Low", "Moderate", "High", "Severe"]
MAX_FLEET = 20
MAX_SITES = 30

MODES: dict[str, dict[str, str]] = {
    "road": {"label": "Road", "source": "OSRM road routing on OpenStreetMap, scaled to the vehicle type, with driver breaks"},
    "rail": {"label": "Rail", "source": "Indian railway network from OpenStreetMap, at the average freight train speed of about 25 km/h"},
    "air": {"label": "Air", "source": "Great-circle route between the nearest scheduled airports, 780 km/h cruise"},
    "sea": {"label": "Sea", "source": "Coastal sea lane between Indian ports, passing south of Sri Lanka between the two coasts"},
}

VEHICLES: dict[str, dict[str, Any]] = {
    "lcv": {"label": "Light truck (LCV)", "factor": 1.25, "high_sided": False, "open_body": True},
    "hcv": {"label": "Heavy truck (HCV)", "factor": 1.5, "high_sided": False, "open_body": True},
    "container": {"label": "Container trailer", "factor": 1.65, "high_sided": True, "open_body": False},
    "tanker": {"label": "Tanker", "factor": 1.55, "high_sided": False, "open_body": False},
    "reefer": {"label": "Reefer truck", "factor": 1.5, "high_sided": True, "open_body": False},
}

CARGO: dict[str, dict[str, Any]] = {
    "general": {"label": "General cargo"},
    "chilled": {"label": "Chilled (2 to 8 °C)", "band": (2.0, 8.0), "controlled": True},
    "frozen": {"label": "Frozen (-18 °C or below)", "band": (-25.0, -18.0), "controlled": True},
    "pharma": {"label": "Pharma, room temperature (15 to 25 °C)", "band": (15.0, 25.0)},
    "produce": {"label": "Fresh produce, no cooling"},
    "moisture": {"label": "Moisture-sensitive (cement, grain, paper, textiles)"},
    "electronics": {"label": "Electronics and fragile goods"},
    "hazmat": {"label": "Flammable or hazardous"},
    "livestock": {"label": "Livestock and poultry"},
}

SEA_KMH = 22.2
RAIL_KMH = 25.0
BREAK_AFTER_S = {1: 4.5 * 3600, 2: 5 * 3600}
BREAK_S = {1: 30 * 60, 2: 20 * 60}
DAY_LIMIT_S = 10 * 3600
FINAL_RUN_S = 2 * 3600
HALT_S = 8 * 3600
MKT_ACTIVATION_K = 10000.0
CARGO_LAG_H = 12.0

SEA_CHAIN: list[tuple[float, float, str]] = [
    (22.85, 70.10, "Gulf of Kutch"),
    (22.70, 69.60, "off Mundra"),
    (22.50, 68.85, "Gulf of Kutch entrance"),
    (21.90, 68.75, "off Dwarka"),
    (21.20, 69.40, "off Porbandar"),
    (20.55, 70.60, "off Veraval"),
    (20.70, 71.55, "off Pipavav"),
    (20.30, 72.20, "Gulf of Khambhat entrance"),
    (18.85, 72.55, "off Mumbai"),
    (17.00, 72.90, "off Ratnagiri"),
    (15.40, 73.55, "off Goa"),
    (14.00, 74.10, "off Karwar"),
    (12.90, 74.55, "off Mangaluru"),
    (11.50, 75.20, "off Kozhikode"),
    (9.95, 75.95, "off Kochi"),
    (8.80, 76.30, "off Kollam"),
    (8.25, 76.85, "off Vizhinjam"),
    (7.60, 77.50, "south of Kanyakumari"),
    (6.50, 79.20, "west of Sri Lanka"),
    (5.75, 80.20, "off Galle"),
    (5.70, 81.00, "off Dondra Head"),
    (6.40, 82.10, "south-east of Sri Lanka"),
    (8.00, 82.20, "east of Sri Lanka"),
    (9.60, 81.30, "north-east of Sri Lanka"),
    (11.00, 80.40, "off Nagapattinam"),
    (13.10, 80.60, "off Chennai"),
    (14.25, 80.45, "off Krishnapatnam"),
    (15.60, 81.40, "off Machilipatnam"),
    (16.60, 82.70, "off Kakinada"),
    (17.55, 83.50, "off Visakhapatnam"),
    (19.10, 85.20, "off Gopalpur"),
    (20.10, 86.95, "off Paradip"),
    (20.70, 87.30, "off Dhamra"),
    (21.10, 88.05, "Sandheads"),
]
BAY_GATE = 22

PORTS: list[dict[str, Any]] = [
    {"id": "kandla", "name": "Deendayal Port, Kandla", "state": "Gujarat", "lat": 23.03, "lon": 70.22, "node": 0},
    {"id": "mundra", "name": "Mundra Port", "state": "Gujarat", "lat": 22.74, "lon": 69.70, "node": 1},
    {"id": "pipavav", "name": "Pipavav Port", "state": "Gujarat", "lat": 20.92, "lon": 71.51, "node": 6},
    {"id": "hazira", "name": "Hazira Port", "state": "Gujarat", "lat": 21.09, "lon": 72.63, "node": 7},
    {"id": "jnpt", "name": "Jawaharlal Nehru Port (Nhava Sheva)", "state": "Maharashtra", "lat": 18.95, "lon": 72.95, "node": 8},
    {"id": "mumbai", "name": "Mumbai Port", "state": "Maharashtra", "lat": 18.94, "lon": 72.84, "node": 8},
    {"id": "mormugao", "name": "Mormugao Port", "state": "Goa", "lat": 15.41, "lon": 73.80, "node": 10},
    {"id": "mangaluru", "name": "New Mangalore Port", "state": "Karnataka", "lat": 12.93, "lon": 74.81, "node": 12},
    {"id": "kochi", "name": "Cochin Port", "state": "Kerala", "lat": 9.97, "lon": 76.27, "node": 14},
    {"id": "vizhinjam", "name": "Vizhinjam International Seaport", "state": "Kerala", "lat": 8.37, "lon": 77.00, "node": 16},
    {"id": "tuticorin", "name": "V.O. Chidambaranar Port, Thoothukudi", "state": "Tamil Nadu", "lat": 8.75, "lon": 78.21, "node": 17, "approach": [(8.30, 78.35)]},
    {"id": "chennai", "name": "Chennai Port", "state": "Tamil Nadu", "lat": 13.10, "lon": 80.30, "node": 25},
    {"id": "ennore", "name": "Kamarajar Port, Ennore", "state": "Tamil Nadu", "lat": 13.26, "lon": 80.34, "node": 25},
    {"id": "kattupalli", "name": "Kattupalli Port", "state": "Tamil Nadu", "lat": 13.31, "lon": 80.35, "node": 25},
    {"id": "krishnapatnam", "name": "Krishnapatnam Port", "state": "Andhra Pradesh", "lat": 14.25, "lon": 80.13, "node": 26},
    {"id": "kakinada", "name": "Kakinada Port", "state": "Andhra Pradesh", "lat": 16.98, "lon": 82.28, "node": 28},
    {"id": "visakhapatnam", "name": "Visakhapatnam Port", "state": "Andhra Pradesh", "lat": 17.69, "lon": 83.29, "node": 29},
    {"id": "gangavaram", "name": "Gangavaram Port", "state": "Andhra Pradesh", "lat": 17.62, "lon": 83.23, "node": 29},
    {"id": "gopalpur", "name": "Gopalpur Port", "state": "Odisha", "lat": 19.30, "lon": 84.96, "node": 30},
    {"id": "paradip", "name": "Paradip Port", "state": "Odisha", "lat": 20.26, "lon": 86.67, "node": 31},
    {"id": "dhamra", "name": "Dhamra Port", "state": "Odisha", "lat": 20.79, "lon": 86.96, "node": 32},
    {"id": "haldia", "name": "Haldia Dock Complex", "state": "West Bengal", "lat": 22.03, "lon": 88.09, "node": 33},
    {"id": "kolkata", "name": "Syama Prasad Mookerjee Port, Kolkata", "state": "West Bengal", "lat": 22.55, "lon": 88.31, "node": 33},
    {"id": "portblair", "name": "Port Blair", "state": "Andaman and Nicobar", "lat": 11.67, "lon": 92.75, "node": -1},
]

HUBS: list[dict[str, Any]] = [
    {"id": "tughlakabad", "name": "ICD Tughlakabad", "city": "Delhi", "lat": 28.50, "lon": 77.29},
    {"id": "dadri", "name": "ICD Dadri", "city": "Greater Noida", "lat": 28.56, "lon": 77.56},
    {"id": "farukhnagar", "name": "Farukhnagar warehousing cluster", "city": "Gurugram", "lat": 28.44, "lon": 76.82},
    {"id": "ludhiana", "name": "ICD Ludhiana", "city": "Ludhiana", "lat": 30.85, "lon": 75.95},
    {"id": "jaipur", "name": "ICD Kanakpura", "city": "Jaipur", "lat": 26.93, "lon": 75.69},
    {"id": "kanpur", "name": "ICD Kanpur", "city": "Kanpur", "lat": 26.42, "lon": 80.33},
    {"id": "sanand", "name": "Sanand logistics zone", "city": "Ahmedabad", "lat": 22.99, "lon": 72.38},
    {"id": "pithampur", "name": "Pithampur industrial area", "city": "Indore", "lat": 22.61, "lon": 75.69},
    {"id": "bhiwandi", "name": "Bhiwandi warehousing cluster", "city": "Mumbai", "lat": 19.30, "lon": 73.06},
    {"id": "chakan", "name": "Chakan logistics zone", "city": "Pune", "lat": 18.76, "lon": 73.86},
    {"id": "mihan", "name": "MIHAN multimodal hub", "city": "Nagpur", "lat": 21.06, "lon": 79.05},
    {"id": "medchal", "name": "Medchal warehousing cluster", "city": "Hyderabad", "lat": 17.63, "lon": 78.48},
    {"id": "vijayawada", "name": "Vijayawada logistics zone", "city": "Vijayawada", "lat": 16.51, "lon": 80.65},
    {"id": "whitefield", "name": "ICD Whitefield", "city": "Bengaluru", "lat": 12.99, "lon": 77.75},
    {"id": "hoskote", "name": "Hoskote warehousing cluster", "city": "Bengaluru", "lat": 13.07, "lon": 77.80},
    {"id": "sriperumbudur", "name": "Sriperumbudur-Oragadam cluster", "city": "Chennai", "lat": 12.97, "lon": 79.94},
    {"id": "coimbatore", "name": "Coimbatore logistics zone", "city": "Coimbatore", "lat": 11.02, "lon": 76.96},
    {"id": "dankuni", "name": "Dankuni freight hub", "city": "Kolkata", "lat": 22.68, "lon": 88.29},
    {"id": "patna", "name": "Patna logistics zone", "city": "Patna", "lat": 25.59, "lon": 85.14},
    {"id": "lucknow", "name": "Lucknow logistics zone", "city": "Lucknow", "lat": 26.85, "lon": 80.95},
    {"id": "guwahati", "name": "Guwahati logistics zone", "city": "Guwahati", "lat": 26.14, "lon": 91.74},
]

CITIES: dict[str, tuple[float, float]] = {
    "Delhi": (28.61, 77.21), "Mumbai": (19.08, 72.88), "Kolkata": (22.57, 88.36), "Chennai": (13.08, 80.27), "Bengaluru": (12.97, 77.59),
    "Hyderabad": (17.39, 78.49), "Ahmedabad": (23.02, 72.57), "Pune": (18.52, 73.86), "Jaipur": (26.91, 75.79), "Lucknow": (26.85, 80.95),
    "Nagpur": (21.15, 79.09), "Guwahati": (26.14, 91.74), "Visakhapatnam": (17.69, 83.22), "Kochi": (9.93, 76.27), "Ludhiana": (30.90, 75.85),
    "Mundra": (22.84, 69.72), "Indore": (22.72, 75.86), "Patna": (25.59, 85.14), "Vijayawada": (16.51, 80.65), "Coimbatore": (11.02, 76.96),
}

LANES: list[tuple[str, str]] = [
    ("Delhi", "Mumbai"), ("Delhi", "Kolkata"), ("Mumbai", "Chennai"), ("Chennai", "Kolkata"), ("Delhi", "Bengaluru"), ("Mumbai", "Bengaluru"),
    ("Bengaluru", "Chennai"), ("Delhi", "Ludhiana"), ("Delhi", "Jaipur"), ("Ahmedabad", "Mumbai"), ("Ahmedabad", "Mundra"), ("Mumbai", "Pune"),
    ("Mumbai", "Nagpur"), ("Nagpur", "Kolkata"), ("Hyderabad", "Visakhapatnam"), ("Bengaluru", "Hyderabad"), ("Chennai", "Kochi"), ("Delhi", "Lucknow"),
    ("Lucknow", "Patna"), ("Kolkata", "Guwahati"), ("Mumbai", "Indore"), ("Hyderabad", "Vijayawada"),
]

_weather_cache = TTLCache(ttl_s=1800)
_shipment_cache = TTLCache(ttl_s=600)
_site_cache = TTLCache(ttl_s=900, max_items=64)
_analysis_cache = TTLCache(ttl_s=1800, max_items=128)
_network_cache = TTLCache(ttl_s=1800, max_items=4)
_lane_lock = asyncio.Lock()
_lane_routes: dict[str, Route] = {}


def risk_label(score: float) -> str:
    return LEVELS[max(0, min(3, int(score)))]


def options() -> dict[str, Any]:
    return {
        "modes": [{"id": k, "label": v["label"]} for k, v in MODES.items()],
        "vehicles": [{"id": k, "label": v["label"]} for k, v in VEHICLES.items()],
        "cargo": [{"id": k, "label": v["label"]} for k, v in CARGO.items()],
        "ports": [{k: p[k] for k in ("id", "name", "state", "lat", "lon")} for p in PORTS],
        "hubs": [{k: h[k] for k in ("id", "name", "city", "lat", "lon")} for h in HUBS],
        "limits": {"fleet": MAX_FLEET, "sites": MAX_SITES, "vias": trips.MAX_VIAS},
    }


async def resolve(place: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(place, str):
        place = {"name": place}
    lat, lon = place.get("lat"), place.get("lon")
    if lat is not None and lon is not None:
        if place.get("name"):
            return {"name": place["name"], "lat": float(lat), "lon": float(lon), "state": place.get("state"), "district": place.get("district")}
        try:
            found = await weather.reverse_geocode(float(lat), float(lon))
        except Exception:
            found = {}
        return {"name": found.get("name") or f"{float(lat):.2f}, {float(lon):.2f}", "lat": float(lat), "lon": float(lon), "state": found.get("state"), "district": found.get("district")}
    name = (place.get("name") or "").strip()
    if not name:
        raise TripError("Each place needs a name or a latitude and longitude")
    known = next((p for p in PORTS + HUBS if name.lower() in (p["id"], p["name"].lower())), None)
    if known:
        return {"name": known["name"], "lat": known["lat"], "lon": known["lon"], "state": known.get("state")}
    hits = await weather.geocode(name)
    india = [h for h in hits if (h.get("country_code") or "IN") == "IN"]
    hit = (india or hits or [None])[0]
    if not hit:
        raise TripError(f"Could not find a place called {name}")
    return {"name": hit["name"], "lat": hit["lat"], "lon": hit["lon"], "state": hit.get("state"), "district": hit.get("district")}


def nearest_port(lat: float, lon: float) -> tuple[dict[str, Any], float]:
    best = min(PORTS, key=lambda p: haversine((lat, lon), (p["lat"], p["lon"])))
    return best, haversine((lat, lon), (best["lat"], best["lon"]))


def _densify(points: list[tuple[float, float]], step_m: float = 25000.0) -> list[tuple[float, float]]:
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        pieces = max(1, math.ceil(haversine(a, b) / step_m))
        out.extend((a[0] + (b[0] - a[0]) * k / pieces, a[1] + (b[1] - a[1]) * k / pieces) for k in range(1, pieces + 1))
    return out


def sea_route(a: dict[str, Any], b: dict[str, Any]) -> Route:
    if a["id"] == b["id"]:
        raise TripError(f"Both places are closest to {a['name']}; a sea leg makes no sense")
    blair = next(p for p in PORTS if p["id"] == "portblair")

    def to_blair(port: dict[str, Any]) -> list[tuple[float, float]]:
        node = port["node"]
        chain = [SEA_CHAIN[k][:2] for k in range(node, BAY_GATE + 1)] if node < BAY_GATE else [SEA_CHAIN[node][:2]]
        return [(port["lat"], port["lon"]), *port.get("approach", []), *chain, (blair["lat"], blair["lon"])]

    if a["id"] == "portblair":
        path = to_blair(b)[::-1]
    elif b["id"] == "portblair":
        path = to_blair(a)
    else:
        i, j = a["node"], b["node"]
        chain = [SEA_CHAIN[k][:2] for k in (range(i, j + 1) if i <= j else range(i, j - 1, -1))]
        path = [(a["lat"], a["lon"]), *a.get("approach", []), *chain, *reversed(b.get("approach", [])), (b["lat"], b["lon"])]
    coords = _densify(path)
    cum_m = cumulative(coords)
    cum_s = [m / (SEA_KMH / 3.6) for m in cum_m]
    extra = {"from_port": {k: a[k] for k in ("id", "name", "state", "lat", "lon")}, "to_port": {k: b[k] for k in ("id", "name", "state", "lat", "lon")}, "speed_knots": round(SEA_KMH / 1.852)}
    return Route(coords, cum_m, cum_s, f"{a['name']} → {b['name']}", "", extra)


async def _batch(url: str, points: list[tuple[float, float]], hourly: str, days: int) -> list[dict[str, Any]]:
    key = hashlib.sha1(json.dumps([url, hourly, days, [[round(p[0], 2), round(p[1], 2)] for p in points]]).encode()).hexdigest()

    async def load() -> list[dict[str, Any]]:
        params = {"latitude": ",".join(f"{p[0]:.3f}" for p in points), "longitude": ",".join(f"{p[1]:.3f}" for p in points), "hourly": hourly, "forecast_days": days, "timezone": "GMT"}
        for wait in (6, 20, 0):
            response = await client().get(url, params=params, timeout=60)
            if response.status_code != 429 or not wait:
                break
            await asyncio.sleep(wait)
        if response.status_code == 429:
            raise TripError("The weather data service is rate-limiting requests; try again in a minute")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    return await _weather_cache.get_or_set(key, load)


async def series_for(points: list[tuple[float, float]], days: int, url: str = weather.FORECAST_URL, hourly: str = LAND_HOURLY, size: int = 40) -> list[dict[str, Any]]:
    chunks = [points[i:i + size] for i in range(0, len(points), size)]
    results = await asyncio.gather(*(_batch(url, chunk, hourly, days) for chunk in chunks))
    return [item for batch in results for item in batch]


def crosswind(gust: float | None, wind_dir: float | None, heading: float | None) -> float:
    if not gust or wind_dir is None or heading is None:
        return 0.0
    return abs(gust * math.sin(math.radians(wind_dir - heading)))


def reductions(w: dict[str, Any], spec: dict[str, Any], heading: float | None = None) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = []
    mode = spec["mode"]
    rain = w.get("precipitation") or 0
    code = w.get("weather_code") or 0
    vis = w.get("visibility")
    gust = w.get("wind_gusts_10m") or 0
    temp = w.get("temperature_2m")
    if mode == "sea":
        wave = w.get("wave_height")
        if wave is not None:
            if wave >= 6:
                out.append(("waves", 0.5, 0.7))
            elif wave >= 4:
                out.append(("waves", 0.3, 0.45))
            elif wave >= 2.5:
                out.append(("waves", 0.15, 0.25))
            elif wave >= 1.5:
                out.append(("waves", 0.05, 0.1))
        if vis is not None and vis < 1000:
            out.append(("fog", 0.2, 0.4))
        return out
    if mode == "air":
        return out
    if mode == "rail":
        if vis is not None and vis < 200:
            out.append(("fog", 0.3, 0.5))
        elif vis is not None and vis < 1000:
            out.append(("fog", 0.1, 0.2))
        if rain >= 20:
            out.append(("rain", 0.2, 0.4))
        if temp is not None and temp >= 45:
            out.append(("heat", 0.1, 0.2))
        return out
    if code in (71, 73, 75, 77, 85, 86):
        out.append(("snow", 0.35, 0.6))
    elif rain >= 20:
        out.append(("rain", 0.3, 0.5))
    elif rain >= 7.6:
        out.append(("rain", 0.16, 0.3))
    elif rain >= 2.5:
        out.append(("rain", 0.1, 0.16))
    elif rain >= 0.2:
        out.append(("rain", 0.06, 0.13))
    if vis is not None:
        if vis < 50:
            out.append(("fog", 0.7, 0.85))
        elif vis < 200:
            out.append(("fog", 0.4, 0.7))
        elif vis < 1000:
            out.append(("fog", 0.11, 0.2))
    if code >= 95:
        out.append(("thunder", 0.05, 0.15))
    if spec.get("high_sided"):
        side = crosswind(gust, w.get("wind_direction_10m"), heading)
        if side >= 65:
            out.append(("wind", 0.25, 0.5))
        elif side >= 50:
            out.append(("wind", 0.1, 0.2))
    elif gust >= 90:
        out.append(("wind", 0.15, 0.3))
    return out


def time_multiplier(cuts: list[tuple[str, float, float]]) -> tuple[float, float]:
    expected = worst = 1.0
    for _, low, high in cuts:
        expected *= 1 - low
        worst *= 1 - high
    return 1 / max(0.12, expected), 1 / max(0.08, worst)


def hazards_at(w: dict[str, Any], spec: dict[str, Any], heading: float | None = None, phase: str = "ground") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(kind: str, level: float, detail: str) -> None:
        out.append({"kind": kind, "level": level, "detail": detail})

    mode = spec["mode"]
    rain = w.get("precipitation") or 0
    code = w.get("weather_code") or 0
    gust = w.get("wind_gusts_10m") or 0
    vis = w.get("visibility")
    temp = w.get("temperature_2m")
    feels = w.get("apparent_temperature")
    if mode == "air":
        return trips.assess(w, "flight", phase)
    if mode == "sea":
        wave = w.get("wave_height")
        if wave is not None:
            if wave >= 6:
                add("waves", 3, f"High sea, significant wave height {wave:.1f} m")
            elif wave >= 4:
                add("waves", 2.5, f"Very rough sea, waves {wave:.1f} m")
            elif wave >= 2.5:
                add("waves", 1.5, f"Rough sea, waves {wave:.1f} m")
        if gust >= 89:
            add("wind", 3, f"Storm-force gusts, {gust:.0f} km/h")
        elif gust >= 63:
            add("wind", 2, f"Gale-force gusts, {gust:.0f} km/h")
        if code >= 95:
            add("thunder", 1.5, "Thunderstorm with squalls")
        if vis is not None and vis < 1000:
            add("fog", 1.5, f"Fog at sea, visibility about {vis:.0f} m")
        return out
    if code >= 95:
        add("thunder", 2.5 if code >= 96 else 2, "Thunderstorm with lightning" + (" and hail" if code >= 96 else ""))
    elif code in (71, 73, 75, 77, 85, 86):
        add("snow", 3, "Snowfall; hill roads and passes can close")
    if rain >= 20:
        add("rain", 3, f"Very heavy rain, {rain:.0f} mm/h; waterlogging and crawl speeds likely")
    elif rain >= 7.6:
        add("rain", 2, f"Heavy rain, {rain:.1f} mm/h")
    elif rain >= 2.5:
        add("rain", 1, f"Moderate rain, {rain:.1f} mm/h")
    if vis is not None:
        if vis < 200:
            add("fog", 3, f"Dense fog, visibility about {vis:.0f} m")
        elif vis < 1000:
            add("fog", 1.5, f"Fog or mist, visibility about {vis:.0f} m")
    if mode == "road":
        side = crosswind(gust, w.get("wind_direction_10m"), heading)
        if spec.get("high_sided") and side >= 65:
            add("wind", 3, f"Crosswind gusts {side:.0f} km/h on a high-sided vehicle; rollover risk on bridges and open stretches")
        elif spec.get("high_sided") and side >= 50:
            add("wind", 2, f"Crosswind gusts {side:.0f} km/h on a high-sided vehicle")
        elif gust >= 90:
            add("wind", 2.5, f"Very strong gusts, {gust:.0f} km/h")
        elif gust >= 70:
            add("wind", 1.5, f"Strong gusts, {gust:.0f} km/h")
        if feels is not None and feels >= 45:
            add("heat", 1, f"Feels like {feels:.0f} °C; tyre and engine stress, driver fatigue")
        if temp is not None and temp <= 0:
            add("cold", 2, f"Freezing, {temp:.0f} °C; ice possible on bridges and hill roads")
    if mode == "rail":
        if temp is not None and temp >= 45:
            add("heat", 1, f"{temp:.0f} °C; speed restrictions possible for rail expansion")
        out = [h | {"level": min(h["level"], 2.5 if h["kind"] == "fog" else 2)} for h in out]
    return out


AIR_GROUND = [("fog", 3, 120, 240), ("fog", 1, 45, 90), ("thunder", 2, 40, 90), ("wind", 1.5, 20, 45)]


def _air_ground_delay(found: list[dict[str, Any]]) -> tuple[float, float]:
    expected = worst = 0.0
    for kind, level, low, high in AIR_GROUND:
        if any(h["kind"] == kind and h["level"] >= level for h in found):
            expected = max(expected, low * 60)
            worst = max(worst, high * 60)
    return expected, worst


def _reading(w: dict[str, Any] | None) -> dict[str, Any] | None:
    if not w:
        return None
    return {
        "temp": w.get("temperature_2m"), "feels": w.get("apparent_temperature"), "dew": w.get("dew_point_2m"), "rh": w.get("relative_humidity_2m"),
        "rain_mmh": w.get("precipitation"), "code": w.get("weather_code"),
        "label": describe(w.get("weather_code") or 0)["label"], "gust": w.get("wind_gusts_10m"),
        "wind_dir": w.get("wind_direction_10m"), "visibility": w.get("visibility"), "is_day": w.get("is_day"),
        "wave": w.get("wave_height"), "swell": w.get("swell_wave_height"), "wave_period": w.get("wave_period"), "elevation": w.get("elevation"),
    }


def simulate(route: Route, picks: list[int], land: list[dict[str, Any]], marine: list[dict[str, Any]] | None, depart: datetime, spec: dict[str, Any]) -> dict[str, Any]:
    mode = spec["mode"]
    crew = spec.get("crew", 1)
    clock = depart
    delay = worst_delay = drive = rest = 0.0
    since_break = today = 0.0
    points: list[dict[str, Any]] = []
    rests: list[dict[str, Any]] = []
    levels: list[float] = []
    causes: dict[str, float] = {}
    last = len(picks) - 1
    for n, i in enumerate(picks):
        w = trips._at(land[n], clock)
        if w is not None and marine is not None:
            sea = trips._at(marine[n], clock)
            if sea:
                w = w | {k: sea.get(k) for k in ("wave_height", "wave_direction", "wave_period", "swell_wave_height")}
        heading = bearing(route.coords[max(0, i - 1)], route.coords[min(len(route.coords) - 1, i + 1)]) if len(route.coords) > 1 else None
        phase = "cruise" if mode == "air" and 0 < n < last and i not in route.stops else "airport" if mode == "air" else "ground"
        found = hazards_at(w, spec, heading, phase) if w else []
        cuts = reductions(w, spec, heading) if w else []
        factor, worst_factor = time_multiplier(cuts)
        level = max((h["level"] for h in found), default=0.0)
        levels.append(level)
        points.append({
            "i": i, "lat": route.coords[i][0], "lon": route.coords[i][1], "km": round(route.cum_m[i] / 1000, 1), "eta": clock.isoformat(),
            "weather": _reading(w), "hazards": found, "level": level, "slow_pct": round((1 - 1 / factor) * 100),
        })
        if mode == "air" and phase == "airport":
            extra, extra_worst = _air_ground_delay(found)
            if extra:
                causes["airport"] = causes.get("airport", 0.0) + extra
            delay += extra
            worst_delay += extra_worst
            clock += timedelta(seconds=extra)
        if n == last:
            break
        base = route.cum_s[picks[n + 1]] - route.cum_s[i]
        moving = base * factor
        delay += moving - base
        weights = {kind: -math.log(1 - low) for kind, low, _ in cuts if low > 0}
        for kind, weight in weights.items():
            causes[kind] = causes.get(kind, 0.0) + (moving - base) * weight / sum(weights.values())
        worst_delay += base * worst_factor - base
        drive += moving
        clock += timedelta(seconds=moving)
        if mode != "road":
            continue
        since_break += moving
        today += moving
        left = route.cum_s[-1] - route.cum_s[picks[n + 1]]
        if left <= FINAL_RUN_S:
            continue
        if today >= DAY_LIMIT_S and crew == 1 and n + 1 < last:
            rests.append({"kind": "halt", "km": round(route.cum_m[picks[n + 1]] / 1000, 1), "at": clock.isoformat(), "minutes": HALT_S // 60, "i": picks[n + 1]})
            clock += timedelta(seconds=HALT_S)
            rest += HALT_S
            since_break = today = 0.0
        elif since_break >= BREAK_AFTER_S[crew] and n + 1 < last:
            rests.append({"kind": "break", "km": round(route.cum_m[picks[n + 1]] / 1000, 1), "at": clock.isoformat(), "minutes": BREAK_S[crew] // 60, "i": picks[n + 1]})
            clock += timedelta(seconds=BREAK_S[crew])
            rest += BREAK_S[crew]
            since_break = 0.0
    covered = [p for p in points if p["weather"]]
    spans = [(route.cum_m[picks[min(k + 1, last)]] - route.cum_m[picks[max(k - 1, 0)]]) / 2 for k in range(len(picks))]
    total = sum(spans) or 1.0
    score = sum(length * level for length, level in zip(spans, levels)) / total + max(levels, default=0.0) * 0.5
    severe_km = sum(length for length, level in zip(spans, levels) if level >= 3) / 1000
    return {
        "points": points, "arrive": clock, "delay_s": delay, "delay_worst_s": max(delay, worst_delay), "drive_s": drive, "rest_s": rest, "rests": rests,
        "score": round(score, 3), "max_level": max(levels, default=0.0), "severe_km": round(severe_km), "coverage": len(covered) / max(1, len(points)), "causes": causes,
        "night": sum(1 for p in covered if p["weather"]["is_day"] == 0) / max(1, len(covered)),
    }


def mean_kinetic(temps: list[float]) -> float | None:
    if not temps:
        return None
    total = sum(math.exp(-MKT_ACTIVATION_K / (t + 273.15)) for t in temps) / len(temps)
    return MKT_ACTIVATION_K / -math.log(total) - 273.15


def heat_humidity_index(temp: float, rh: float) -> float:
    return 0.8 * temp + rh / 100 * (temp - 14.4) + 46.4


def cargo_exposure(points: list[dict[str, Any]], cargo: str, spec: dict[str, Any]) -> dict[str, Any]:
    info = CARGO[cargo]
    timeline = [(datetime.fromisoformat(p["eta"]), p["weather"]) for p in points if p["weather"] and p["weather"].get("temp") is not None]
    out: dict[str, Any] = {"id": cargo, "label": info["label"], "status": "ok", "metrics": [], "notes": []}
    if len(timeline) < 2:
        return out
    hours = [max(0.0, (b[0] - a[0]).total_seconds() / 3600) for a, b in zip(timeline, timeline[1:])] + [0.0]
    temps = [w["temp"] for _, w in timeline]
    peak, low = max(temps), min(temps)

    def span(test) -> float:
        return round(sum(h for h, (_, w) in zip(hours, timeline) if test(w)), 1)

    def metric(label: str, value: str) -> None:
        out["metrics"].append({"label": label, "value": value})

    def raise_to(status: str) -> None:
        order = ["ok", "watch", "risk"]
        if order.index(status) > order.index(out["status"]):
            out["status"] = status

    rain_mm = round(sum((w.get("rain_mmh") or 0) * h for h, (_, w) in zip(hours, timeline)), 1)
    lagged = temps[0]
    sweat = 0.0
    for h, (_, w) in zip(hours, timeline):
        if w.get("dew") is not None and w["dew"] > lagged + 0.5:
            sweat += h
        lagged += (w["temp"] - lagged) * min(1.0, h / CARGO_LAG_H)
    loaded_dew = timeline[0][1].get("dew")
    drip = span(lambda w: loaded_dew is not None and w["temp"] < loaded_dew - 1)
    humid = span(lambda w: (w.get("rh") or 0) >= 85)
    metric("Outside temperature", f"{low:.0f} to {peak:.0f} °C")

    if cargo in ("chilled", "frozen"):
        hot = span(lambda w: w["temp"] >= 35)
        very_hot = span(lambda w: w["temp"] >= 40)
        setpoint = info["band"][1]
        metric("Hours above 35 °C outside", f"{hot:g} h")
        metric("Largest gap to setpoint", f"{peak - setpoint:.0f} °C")
        if very_hot >= 2:
            raise_to("risk")
            out["notes"].append(f"{very_hot:g} hours above 40 °C: the refrigeration unit runs near full load. Pre-cool the body and the cargo to setpoint, check genset fuel, and keep door openings short.")
        elif hot >= 3:
            raise_to("watch")
            out["notes"].append(f"{hot:g} hours above 35 °C: expect higher fuel use by the refrigeration unit. Load only pre-cooled product.")
        if spec.get("vehicle") not in ("reefer", None) and spec["mode"] == "road":
            raise_to("risk")
            out["notes"].append("This cargo needs a refrigerated vehicle; the selected vehicle is not one.")
    elif cargo == "pharma":
        outside = span(lambda w: w["temp"] > 25 or w["temp"] < 15)
        above30 = span(lambda w: w["temp"] > 30)
        kinetic = mean_kinetic(temps)
        metric("Hours outside 15 to 25 °C", f"{outside:g} h")
        if kinetic is not None:
            metric("Mean kinetic temperature of outside air", f"{kinetic:.1f} °C")
        if above30 >= 1 or (kinetic is not None and kinetic > 25):
            raise_to("risk")
            out["notes"].append("Outside air goes above the 15 to 25 °C label range for long enough that an uncontrolled load would record an excursion. Use a temperature-controlled or insulated shipper with a data logger.")
        elif outside >= 2:
            raise_to("watch")
            out["notes"].append("Outside air leaves the 15 to 25 °C range for part of the trip. Passive insulation is advisable.")
    elif cargo == "produce":
        warm = span(lambda w: w["temp"] >= 30)
        rate = sum(h * 2.5 ** ((w["temp"] - 20) / 10) for h, (_, w) in zip(hours, timeline)) / max(0.1, sum(hours))
        metric("Hours at 30 °C or more", f"{warm:g} h")
        metric("Ripening and spoilage speed", f"{rate:.1f}× the rate at 20 °C")
        if rate >= 2.2 or warm >= 8:
            raise_to("risk")
            out["notes"].append("Heat along this trip more than doubles the spoilage rate. Move at night, ventilate the load, or use a reefer.")
        elif rate >= 1.5 or warm >= 3:
            raise_to("watch")
            out["notes"].append("Warm stretches shorten shelf life. Load in the cool hours and avoid midday halts in the sun.")
    elif cargo == "livestock":
        index = [heat_humidity_index(w["temp"], w.get("rh") or 50) for _, w in timeline]
        danger = round(sum(h for h, v in zip(hours, index) if v >= 79), 1)
        emergency = round(sum(h for h, v in zip(hours, index) if v >= 84), 1)
        metric("Peak temperature-humidity index", f"{max(index):.0f}")
        metric("Hours in the danger band (79+)", f"{danger:g} h")
        if emergency >= 1:
            raise_to("risk")
            out["notes"].append(f"{emergency:g} hours in the emergency heat band (index 84 or more). Do not move animals in these hours; travel at night with water stops.")
        elif danger >= 1:
            raise_to("watch")
            out["notes"].append("Heat stress is likely for part of the trip. Reduce loading density, keep the vehicle moving and water the animals at halts.")
        if low <= 5:
            raise_to("watch")
            out["notes"].append(f"Cold down to {low:.0f} °C: protect young animals and poultry from wind chill.")
    elif cargo == "hazmat":
        storms = span(lambda w: (w.get("code") or 0) >= 95)
        hot = span(lambda w: w["temp"] >= 40)
        metric("Hours in thunderstorms", f"{storms:g} h")
        metric("Hours at 40 °C or more", f"{hot:g} h")
        if storms >= 1:
            raise_to("risk")
            out["notes"].append("Lightning along the route. Do not load, unload or vent during thunderstorms; park away from tall isolated objects.")
        if hot >= 2:
            raise_to("watch")
            out["notes"].append("Sustained heat raises tank and drum pressure. Check relief valves and avoid parking in direct sun.")

    if cargo in ("moisture", "electronics", "general", "produce"):
        exposed = spec.get("open_body") and spec["mode"] == "road"
        sensitive = cargo in ("moisture", "electronics")
        metric("Rain on the load path", f"{rain_mm:g} mm")
        if sensitive:
            metric("Hours at 85% humidity or more", f"{humid:g} h")
            metric("Hours with condensation risk", f"{round(sweat + drip, 1):g} h")
        if rain_mm >= 10 and exposed:
            raise_to("risk" if sensitive else "watch")
            out["notes"].append(f"About {rain_mm:g} mm of rain falls on an open-body vehicle. Use double tarpaulin with sealed joints and dunnage under the load.")
        elif rain_mm >= 2 and exposed and sensitive:
            raise_to("watch")
            out["notes"].append("Light rain on an open-body vehicle. Tarpaulin the load before departure.")
        if sensitive and sweat >= 2:
            raise_to("watch")
            out["notes"].append(f"Cargo sweat is likely for about {sweat:g} hours: the load stays cooler than the dew point of the air it moves into. Use desiccants and avoid opening doors on arrival until the load warms up.")
        if sensitive and drip >= 2 and not spec.get("open_body"):
            raise_to("watch")
            out["notes"].append(f"Container rain is possible for about {drip:g} hours: outside air cools below the dew point sealed in at loading. Add desiccant bags and a ceiling liner.")
    return out


KIND_WORDS = {
    "rain": "Rain", "fog": "Fog and low visibility", "wind": "Wind", "thunder": "Thunderstorms", "snow": "Snow", "heat": "Heat", "cold": "Cold",
    "waves": "Sea state", "convection": "Storms en route", "jet": "Jet-level winds", "airport": "Airport ground delay",
}


def _weights(points: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    last = len(points) - 1
    km = [(points[min(k + 1, last)]["km"] - points[max(k - 1, 0)]["km"]) / 2 for k in range(len(points))]
    times = [datetime.fromisoformat(p["eta"]) for p in points]
    hours = [(times[min(k + 1, last)] - times[max(k - 1, 0)]).total_seconds() / 7200 for k in range(len(points))]
    return km, hours


def breakdown(run: dict[str, Any]) -> list[dict[str, Any]]:
    points = run["points"]
    km, hours = _weights(points)
    rows: dict[str, dict[str, Any]] = {}
    for p, length, span in zip(points, km, hours):
        for h in p["hazards"]:
            row = rows.setdefault(h["kind"], {"kind": h["kind"], "label": KIND_WORDS.get(h["kind"], h["kind"].title()), "km": 0.0, "hours": 0.0, "level": 0.0, "worst": h["detail"], "delay_min": 0})
            row["km"] += length
            row["hours"] += span
            if h["level"] >= row["level"]:
                row["level"] = h["level"]
                row["worst"] = h["detail"]
    for kind, seconds in run["causes"].items():
        row = rows.setdefault(kind, {"kind": kind, "label": KIND_WORDS.get(kind, kind.title()), "km": 0.0, "hours": 0.0, "level": 0.0, "worst": "Light conditions that slow traffic slightly", "delay_min": 0})
        row["delay_min"] = round(seconds / 60)
    out = [r | {"km": round(r["km"]), "hours": round(r["hours"], 1), "severity": risk_label(r["level"])} for r in rows.values()]
    return sorted(out, key=lambda r: (-r["level"], -r["delay_min"]))


def stages(run: dict[str, Any], count: int = 8) -> list[dict[str, Any]]:
    points = run["points"]
    if len(points) < 3:
        return []
    cuts = sorted({round(k * (len(points) - 1) / min(count, len(points) - 1)) for k in range(min(count, len(points) - 1) + 1)})
    out = []
    for a, b in zip(cuts, cuts[1:]):
        chunk = [p for p in points[a:b + 1] if p["weather"]]
        if not chunk:
            continue
        readings = [p["weather"] for p in chunk]
        hazards = [h for p in chunk for h in p["hazards"]]
        worst = max(hazards, key=lambda h: h["level"], default=None)
        hours = (datetime.fromisoformat(points[b]["eta"]) - datetime.fromisoformat(points[a]["eta"])).total_seconds() / 3600
        temps = [r["temp"] for r in readings if r["temp"] is not None]
        rates = [r["rain_mmh"] or 0 for r in readings]
        gusts = [r["gust"] for r in readings if r["gust"] is not None]
        sight = [r["visibility"] for r in readings if r["visibility"] is not None]
        waves = [r["wave"] for r in readings if r.get("wave") is not None]
        out.append({
            "from": points[a].get("place"), "to": points[b].get("place"), "from_km": points[a]["km"], "to_km": points[b]["km"], "from_eta": points[a]["eta"], "to_eta": points[b]["eta"],
            "hours": round(hours, 1), "temp_min": round(min(temps)) if temps else None, "temp_max": round(max(temps)) if temps else None,
            "rain_mm": round(sum(rates) / len(rates) * hours, 1), "rain_peak": round(max(rates), 1), "gust_max": round(max(gusts)) if gusts else None,
            "vis_min": round(min(sight)) if sight else None, "wave_max": round(max(waves), 1) if waves else None,
            "sky": max((r["label"] for r in readings), key=[r["label"] for r in readings].count),
            "level": max((p["level"] for p in chunk), default=0.0), "slow_pct": max((p["slow_pct"] for p in chunk), default=0),
            "worst": worst["detail"] if worst else None, "night": sum(1 for r in readings if r["is_day"] == 0) / len(readings) >= 0.5,
        })
    return out


def extremes(run: dict[str, Any]) -> list[dict[str, Any]]:
    seen = [p for p in run["points"] if p["weather"]]
    out = []

    def add(label: str, key: str, pick, unit: str, digits: int = 0) -> None:
        having = [p for p in seen if p["weather"].get(key) is not None]
        if not having:
            return
        p = pick(having, key=lambda q: q["weather"][key])
        value = p["weather"][key]
        out.append({"label": label, "value": f"{value:.{digits}f} {unit}".strip(), "km": p["km"], "eta": p["eta"], "place": p.get("place")})

    add("Hottest", "temp", max, "°C")
    add("Coolest", "temp", min, "°C")
    add("Heaviest rain", "rain_mmh", max, "mm/h", 1)
    add("Strongest gusts", "gust", max, "km/h")
    add("Lowest visibility", "visibility", min, "m")
    add("Most humid", "rh", max, "%")
    add("Highest waves", "wave", max, "m", 1)
    add("Highest ground", "elevation", max, "m")
    return [row for row in out if not (row["label"] == "Heaviest rain" and row["value"].startswith("0.0"))]


async def model_check(run: dict[str, Any]) -> list[dict[str, Any]]:
    points = run["points"]
    chosen = [("Start", points[0]), ("Midway", points[len(points) // 2]), ("Destination", points[-1])]

    async def one(label: str, p: dict[str, Any]) -> dict[str, Any] | None:
        try:
            compare = await weather.compare_models(p["lat"], p["lon"])
        except Exception as exc:
            log.info("model comparison unavailable: %s", exc)
            return None
        local = datetime.fromisoformat(p["eta"]).astimezone(IST).strftime("%Y-%m-%d")
        day = next((d for d in compare["days"] if d["date"] == local), None)
        score = next((c for c in weather.confidence(compare) if c["date"] == local), None)
        if not day or not score:
            return None
        return {
            "where": label, "place": p.get("place"), "km": p["km"], "date": local, "score": score["score"], "label": score["label"], "rain_agreement": score["rain_agreement"],
            "models": [{"name": name, "rain_mm": day[key]["rain"], "tmax": day[key]["tmax"], "gust": day[key]["gust"]} for key, name in compare["models"].items()],
        }

    found = await asyncio.gather(*(one(label, p) for label, p in chosen))
    return [f for f in found if f]


def confidence(run: dict[str, Any], now: datetime, checks: list[dict[str, Any]]) -> dict[str, Any]:
    lead = (run["arrive"] - now).total_seconds() / 3600
    by_lead = 85 if lead <= 48 else 65 if lead <= 96 else 45 if lead <= 168 else 30
    score = round(min([by_lead] + [c["score"] for c in checks]))
    label = "High" if score >= 75 else "Medium" if score >= 50 else "Low"
    note = (
        "The whole trip falls within two days, where hourly forecasts are most dependable." if lead <= 48
        else "Part of the trip is three to four days ahead; timing of rain and fog can shift by several hours." if lead <= 96
        else "Part of the trip is more than four days ahead; treat the later stretches as an outlook and re-check before dispatch."
    )
    if checks and min(c["score"] for c in checks) < 50:
        note += " The weather models disagree at one or more checkpoints."
    return {"score": score, "label": label, "lead_hours": round(lead), "note": note}


def _ist(value: str | datetime) -> str:
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    return moment.astimezone(IST).strftime("%a %d %b, %H:%M")


def _length(minutes: float) -> str:
    total = max(0, round(minutes))
    days, hours, mins = total // 1440, (total % 1440) // 60, total % 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    return f"{mins} min"


def narrative(route: dict[str, Any], origin: str, destination: str, spec: dict[str, Any], cargo_label: str) -> list[str]:
    mode = MODES[spec["mode"]]["label"].lower()
    lines = [
        f"{route['verdict']['label']}. A {mode} shipment of {cargo_label.lower()} from {origin} to {destination} covers {route['distance_km']:,.0f} km. "
        f"Dispatched {_ist(route['depart'])} IST, it is expected to arrive {_ist(route['arrive'])} IST, {_length(route['duration_min'])} later."
    ]
    if route["delay_min"] >= 5:
        causes = [f"{row['label'].lower()} ({_length(row['delay_min'])})" for row in route["breakdown"] if row["delay_min"] >= 3]
        lines.append(
            f"Weather adds about {_length(route['delay_min'])} to the moving time" + (f", mainly from {', '.join(causes[:3])}" if causes else "")
            + f". If conditions sit at the bad end of the forecast range the delay could reach {_length(route['delay_worst_min'])}, for an arrival no later than {_ist(route['arrive_latest'])} IST."
        )
    else:
        lines.append("The forecast shows no weather that slows the shipment on any stretch at the time it passes.")
    if route["hazards"]:
        worst = route["hazards"][0]
        where = f" near {worst['near']}" if worst.get("near") else ""
        lines.append(
            f"The most serious stretch is km {worst['from_km']:.0f} to {worst['to_km']:.0f}{where}, reached around {_ist(worst['from_eta'])} IST: {worst['detail']}. "
            f"In all, {len(route['hazards'])} hazard stretch{'es are' if len(route['hazards']) != 1 else ' is'} on the route."
        )
    if route["rest_min"]:
        halts = sum(1 for r in route["rests"] if r["kind"] == "halt")
        breaks = len(route["rests"]) - halts
        lines.append(f"Driver rest takes {_length(route['rest_min'])}: {halts} overnight halt{'s' if halts != 1 else ''} and {breaks} short break{'s' if breaks != 1 else ''}.")
    live = [w for w in route["warnings"] if w["active_on_arrival"]]
    if live:
        lines.append(f"{len(live)} official warning{'s' if len(live) != 1 else ''} cover part of the route when the shipment is there, the most severe being {live[0]['event']} ({live[0]['severity']}) between km {live[0]['from_km']} and {live[0]['to_km']}.")
    if route["cyclones"]:
        storm = route["cyclones"][0]
        lines.append(f"Cyclone {storm.get('name') or 'system'} is forecast to pass within {storm['closest_km']} km of the route near km {storm['route_km']:.0f}.")
    cargo = route["cargo"]
    lines.append(
        {"ok": "The cargo is not threatened by the weather on this trip.", "watch": "The cargo needs attention on this trip.", "risk": "The cargo is at risk on this trip."}[cargo["status"]]
        + (" " + " ".join(cargo["notes"][:2]) if cargo["notes"] else "")
    )
    if route["best_departure"]:
        lines.append(route["best_departure"]["why"])
    lines.append(f"Forecast confidence is {route['confidence']['label'].lower()} ({route['confidence']['score']} out of 100). {route['confidence']['note']}")
    return lines


def _pick(route: Route, limit: int) -> list[int]:
    return trips.sample(route, limit)


async def route_for(mode: str, waypoints: list[tuple[float, float]], vehicle: str) -> list[Route]:
    if mode == "road":
        found = await trips._osrm("car", waypoints, VEHICLES[vehicle]["factor"], alternatives=True)
    elif mode == "rail":
        route = await asyncio.to_thread(trips._rail_legs, waypoints)
        found = [Route(route.coords, route.cum_m, [m / (RAIL_KMH / 3.6) for m in route.cum_m], route.summary, "", dict(route.extra), list(route.stops))]
    elif mode == "air":
        route = trips._air_legs(waypoints)
        found = [Route(route.coords, route.cum_m, list(route.cum_s), route.summary, "", dict(route.extra), list(route.stops))]
    else:
        ends = [nearest_port(*p) for p in (waypoints[0], waypoints[-1])]
        for (port, gap), label in zip(ends, ("start", "destination")):
            if gap > 250000:
                raise TripError(f"No Indian port within 250 km of the {label}")
        found = [sea_route(ends[0][0], ends[1][0])]
        found[0].extra["from_port"]["km_from_origin"] = round(ends[0][1] / 1000)
        found[0].extra["to_port"]["km_from_destination"] = round(ends[1][1] / 1000)
    for route in found:
        route.source = MODES[mode]["source"]
    return found


def _thin_path(route: Route, limit: int = 240) -> list[tuple[int, float, float]]:
    step = max(1, len(route.coords) // limit)
    return [(i, *route.coords[i]) for i in range(0, len(route.coords), step)]


async def warnings_on(route: Route, eta_at: dict[int, datetime] | None = None) -> list[dict[str, Any]]:
    try:
        board = await fieldmap.warnings()
    except Exception as exc:
        log.info("warning polygons unavailable: %s", exc)
        return []
    path = _thin_path(route)
    found = []
    for item in board["warnings"]:
        if not item["rings"]:
            continue
        hit = next((p for p in path if any(cyclones.inside((p[1], p[2]), ring) for ring in item["rings"])), None)
        if hit is None:
            continue
        exit_point = next((p for p in reversed(path) if any(cyclones.inside((p[1], p[2]), ring) for ring in item["rings"])), hit)
        entry = {
            "id": item["id"], "event": item["event"], "severity": item["severity"], "headline": item["headline"], "issuer": item["issuer"], "expires": item["expires"],
            "from_km": round(route.cum_m[hit[0]] / 1000), "to_km": round(route.cum_m[exit_point[0]] / 1000), "active_on_arrival": True,
        }
        if eta_at and item.get("expires"):
            nearest = min(eta_at, key=lambda i: abs(i - hit[0]))
            try:
                entry["active_on_arrival"] = datetime.fromisoformat(item["expires"]) > eta_at[nearest]
            except ValueError:
                pass
        found.append(entry)
    rank = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    found.sort(key=lambda a: (not a["active_on_arrival"], rank.get(a["severity"] or "", 4), a["from_km"]))
    return found[:12]


async def cyclones_on(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        active = (await cyclones.storms())["active"]
    except Exception as exc:
        log.info("cyclone feed unavailable: %s", exc)
        return []
    probes = points[:: max(1, len(points) // 8)] + [points[-1]]
    out = []
    for storm in active:
        best = None
        for p in probes:
            try:
                hit = cyclones.impact(storm, p["lat"], p["lon"])
            except Exception:
                continue
            near = (hit.get("closest") or {}).get("km")
            if near is None:
                continue
            if best is None or near < best[0]:
                best = (near, p, hit)
        if best and (best[0] <= 400 or best[2].get("in_cone")):
            out.append({
                "name": storm.get("name"), "grade": (storm.get("now") or {}).get("grade"), "closest_km": round(best[0]), "route_km": best[1]["km"],
                "closest_time": (best[2].get("closest") or {}).get("time"), "in_cone": best[2].get("in_cone"), "stage": best[2].get("stage"),
            })
    return out


def verdict(run: dict[str, Any], cargo: dict[str, Any], official: list[dict[str, Any]], storms: list[dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    code = "go"
    live = [w for w in official if w["active_on_arrival"]]
    if storms and any(s.get("stage") or s["closest_km"] <= 200 for s in storms):
        code = "hold"
        storm = storms[0]
        reasons.append(f"Cyclone {storm.get('name') or 'system'} passes within {storm['closest_km']} km of the route")
    if run["severe_km"] >= 20 or run["score"] >= 2.2:
        code = "hold"
        worst = max((h for p in run["points"] for h in p["hazards"]), key=lambda h: h["level"], default=None)
        reasons.append(f"Severe conditions over about {run['severe_km']} km" + (f": {worst['detail']}" if worst else ""))
    if any(w["severity"] == "Extreme" for w in live):
        code = "hold"
        reasons.append("An official extreme-severity warning covers part of the route")
    if code != "hold":
        if cargo["status"] == "risk":
            code = "caution"
            reasons.append("The cargo is at risk from the weather on this trip")
        if run["score"] >= 1 or run["max_level"] >= 2:
            code = "caution"
            reasons.append("Hazardous weather on part of the route")
        if live:
            code = "caution"
            reasons.append(f"{len(live)} official warning{'s' if len(live) != 1 else ''} on the route")
        if run["delay_s"] >= 3600:
            code = "caution"
            reasons.append(f"Weather adds about {round(run['delay_s'] / 60)} minutes")
    elif cargo["status"] == "risk":
        reasons.append("The cargo is at risk from the weather on this trip")
    if not reasons:
        reasons.append("No significant weather on the route at the times the shipment passes")
    labels = {"go": "Go", "caution": "Go with caution", "hold": "Hold or reroute"}
    return {"code": code, "label": labels[code], "reasons": reasons}


ROAD_ACTIONS = {
    "rain": "Reduce speed on wet stretches and avoid underpasses and low causeways that flood.",
    "fog": "Schedule the foggy stretch for after mid-morning or add buffer; use fog lamps and convoy discipline.",
    "wind": "Slow down on bridges, flyovers and open stretches; empty or lightly loaded high-sided vehicles are most at risk.",
    "thunder": "Do not halt under trees or beside metal structures during lightning; stay in the cab.",
    "snow": "Check pass and ghat road status before dispatch; carry chains.",
    "heat": "Check tyre pressure and coolant; plan driver breaks in shade and carry water.",
    "cold": "Watch for ice on bridges and shaded hill roads in the early hours.",
}
OTHER_ACTIONS = {
    "sea": {"waves": "Secure and re-lash cargo; expect slow steaming or a wait for a weather window.", "wind": "Check the port's wind limits for berthing and crane work before arrival.", "fog": "Expect restricted pilotage and vessel movement in fog.", "thunder": "Deck and crane work stops during lightning."},
    "rail": {"fog": "Expect speed restrictions and late running in dense fog.", "rain": "Waterlogged track can hold trains; check for diversions.", "heat": "Hot-weather speed restrictions may apply in the afternoon."},
    "air": {"fog": "Low visibility can hold departures and arrivals; book earlier cut-offs.", "thunder": "Thunderstorms at the airport stop ramp handling and loading.", "wind": "Gusty winds can slow turnarounds.", "convection": "Storms en route can mean detours and a later arrival.", "jet": "Jet-level winds change the flight time."},
}


def actions_for(run: dict[str, Any], cargo: dict[str, Any], spec: dict[str, Any], recommend: dict[str, Any] | None) -> list[str]:
    kinds = []
    for p in run["points"]:
        for h in p["hazards"]:
            if h["level"] >= 1 and h["kind"] not in kinds:
                kinds.append(h["kind"])
    table = ROAD_ACTIONS if spec["mode"] == "road" else OTHER_ACTIONS.get(spec["mode"], {})
    out = [table[k] for k in kinds if k in table]
    out.extend(cargo["notes"])
    if recommend:
        out.insert(0, recommend["why"])
    return out[:8]


def _brief_point(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("lat", "lon", "km", "eta", "level")}


async def analyse(route: Route, depart: datetime, now: datetime, spec: dict[str, Any], cargo: str, detail: bool) -> dict[str, Any]:
    picks = _pick(route, 32)
    points = [route.coords[i] for i in picks]
    base_s = route.seconds
    horizon_h = (depart - now).total_seconds() / 3600 + base_s * 1.6 / 3600 + 60
    days = max(3, min(14, math.ceil(horizon_h / 24) + 1))
    land = await series_for(points, days, hourly=AIR_HOURLY if spec["mode"] == "air" else LAND_HOURLY)
    marine = await series_for(points, min(8, days), weather.MARINE_URL, MARINE_HOURLY) if spec["mode"] == "sea" else None
    run = simulate(route, picks, land, marine, depart, spec)
    for k, p in enumerate(run["points"]):
        p["i_prev"] = run["points"][k - 1]["i"] if k else -1
    scan: list[dict[str, Any]] = []
    step = 1 if base_s < 30 * 3600 else 2
    for hours in range(0, 49, step):
        start = depart + timedelta(hours=hours)
        trial = run if hours == 0 else simulate(route, picks, land, marine, start, spec)
        if trial["coverage"] < 0.9:
            break
        scan.append({"depart": start.isoformat(), "arrive": trial["arrive"].isoformat(), "score": trial["score"], "risk": risk_label(trial["score"]), "delay_min": round(trial["delay_s"] / 60), "night": round(trial["night"], 2)})
    recommend = None
    if scan:
        best = min(scan, key=lambda d: (round(d["score"], 1), d["delay_min"], d["depart"]))
        first = scan[0]
        if best["depart"] != first["depart"] and (first["score"] - best["score"] >= 0.4 or first["delay_min"] - best["delay_min"] >= 45):
            wait = round((datetime.fromisoformat(best["depart"]) - depart).total_seconds() / 3600)
            saved = first["delay_min"] - best["delay_min"]
            recommend = best | {"why": f"Dispatching {wait} h later lowers the risk from {first['risk'].lower()} to {best['risk'].lower()}" + (f" and saves about {saved} minutes of weather delay." if saved >= 15 else ".")}
    eta_at = {p["i"]: datetime.fromisoformat(p["eta"]) for p in run["points"]}
    official, storms = await asyncio.gather(warnings_on(route, eta_at), cyclones_on(run["points"]))
    load = cargo_exposure(run["points"], cargo, spec)
    call = verdict(run, load, official, storms, spec)
    names: dict[int, str] = {}
    if detail and spec["mode"] in ("road", "rail"):
        places = await trips._places(route, picks)
        names = {i: p.get("name") for i, p in places.items() if p.get("name")}
        for p in run["points"]:
            if p["i"] in names:
                p["place"] = names[p["i"]]
    if spec["mode"] == "sea":
        names = {i: min(SEA_CHAIN, key=lambda node: haversine(route.coords[i], node[:2]))[2] for i in picks}
    hazard_spans = trips.spans(run["points"], "car", names)
    guide = ROAD_ACTIONS if spec["mode"] == "road" else OTHER_ACTIONS.get(spec["mode"], {})
    for item in hazard_spans:
        item["advice"] = guide.get(item["kind"], "")
    for rest in run["rests"]:
        if names:
            rest["near"] = names[min(names, key=lambda i: abs(i - rest["i"]))]
        rest.pop("i", None)
    for p in run["points"]:
        p.pop("i_prev", None)
    if spec["mode"] == "air":
        await trips._airport_weather(route.extra)
    if detail and route.summary in ("", "Main route") and names:
        middle = names[min(names, key=lambda i: abs(i - len(route.coords) // 2))]
        route.summary = f"via {middle}"
    arrive = run["arrive"]
    checks = await model_check(run) if detail and spec["mode"] != "air" else []
    other = None
    if detail and spec["mode"] == "road":
        swapped = simulate(route, picks, land, marine, depart, spec | {"crew": 2 if spec["crew"] == 1 else 1})
        other = {"crew": 2 if spec["crew"] == 1 else 1, "arrive": swapped["arrive"].isoformat(), "duration_min": round((swapped["arrive"] - depart).total_seconds() / 60), "rest_min": round(swapped["rest_s"] / 60)}
    result = {
        "summary": route.summary, "source": route.source, "distance_km": round(route.meters / 1000, 1),
        "base_min": round(base_s / 60), "drive_min": round(run["drive_s"] / 60), "rest_min": round(run["rest_s"] / 60),
        "delay_min": round(run["delay_s"] / 60), "delay_worst_min": round(run["delay_worst_s"] / 60), "duration_min": round((arrive - depart).total_seconds() / 60),
        "depart": depart.isoformat(), "arrive": arrive.isoformat(), "arrive_latest": (arrive + timedelta(seconds=run["delay_worst_s"] - run["delay_s"])).isoformat(),
        "risk": {"score": run["score"], "label": risk_label(run["score"])}, "verdict": call, "actions": actions_for(run, load, spec, recommend),
        "cargo": load, "hazards": hazard_spans, "rests": run["rests"], "warnings": official, "cyclones": storms,
        "departures": scan, "best_departure": recommend, "night_share": round(run["night"], 2), "coverage": round(run["coverage"], 2), "extra": route.extra,
        "breakdown": breakdown(run), "confidence": confidence(run, now, checks),
    }
    if detail:
        result["geometry"] = trips._simplify(route.coords)
        result["points"] = run["points"]
        result["stages"] = stages(run)
        result["extremes"] = extremes(run)
        result["model_check"] = checks
        result["other_crew"] = other
        result["top_departures"] = sorted(scan, key=lambda d: (round(d["score"], 1), d["delay_min"], d["depart"]))[:5]
    else:
        result["points"] = [_brief_point(p) for p in run["points"]]
    return result


def parse_depart(value: str | datetime | None, now: datetime) -> datetime:
    if value is None or value == "":
        return now
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TripError("depart must be an ISO date-time like 2026-10-05T21:00") from exc
    when = (value if value.tzinfo else value.replace(tzinfo=IST)).astimezone(timezone.utc)
    if when < now - timedelta(minutes=30):
        return now
    if when > now + timedelta(days=10):
        raise TripError("Weather along the route is only reliable for dispatches in the next 10 days")
    return when


async def shipment(request: dict[str, Any], detail: bool = True) -> dict[str, Any]:
    mode = request.get("mode") or "road"
    vehicle = request.get("vehicle") or "hcv"
    cargo = request.get("cargo") or "general"
    crew = 2 if int(request.get("crew") or 1) >= 2 else 1
    if mode not in MODES:
        raise TripError(f"Unknown mode {mode}; use road, rail, air or sea")
    if vehicle not in VEHICLES:
        raise TripError(f"Unknown vehicle {vehicle}")
    if cargo not in CARGO:
        raise TripError(f"Unknown cargo {cargo}")
    vias_in = list(request.get("vias") or [])
    if len(vias_in) > trips.MAX_VIAS:
        raise TripError(f"At most {trips.MAX_VIAS} stops on the way")
    origin, destination = await asyncio.gather(resolve(request.get("origin") or {}), resolve(request.get("destination") or {}))
    vias = [await resolve(v) for v in vias_in] if mode in ("road", "rail", "air") else []
    waypoints = [(origin["lat"], origin["lon"]), *((v["lat"], v["lon"]) for v in vias), (destination["lat"], destination["lon"])]
    for a, b in zip(waypoints, waypoints[1:]):
        if haversine(a, b) < 2000:
            raise TripError("Two places in a row are the same")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    depart = parse_depart(request.get("depart"), now)
    spec = {"mode": mode, "vehicle": vehicle if mode == "road" else None, "crew": crew, "high_sided": mode == "road" and VEHICLES[vehicle]["high_sided"], "open_body": mode == "road" and VEHICLES[vehicle]["open_body"]}
    key = hashlib.sha1(json.dumps([mode, vehicle, cargo, crew, [[round(a, 3), round(b, 3)] for a, b in waypoints], depart.strftime("%Y%m%d%H"), detail]).encode()).hexdigest()

    async def load() -> dict[str, Any]:
        routes = await route_for(mode, waypoints, vehicle)
        results = [await analyse(route, depart, now, spec, cargo, detail) for route in routes[: 3 if detail else 1]]
        order = {"go": 0, "caution": 1, "hold": 2}
        results.sort(key=lambda r: (order[r["verdict"]["code"]], round(r["risk"]["score"], 1), r["duration_min"]))
        for item in results:
            item["narrative"] = narrative(item, origin["name"], destination["name"], spec, CARGO[cargo]["label"])
        return {
            "mode": mode, "mode_label": MODES[mode]["label"], "vehicle": vehicle if mode == "road" else None, "vehicle_label": VEHICLES[vehicle]["label"] if mode == "road" else None,
            "cargo": cargo, "cargo_label": CARGO[cargo]["label"], "crew": crew, "origin": origin, "destination": destination, "vias": vias,
            "generated_at": now.isoformat(), "routes": results,
            "method": {
                "eta": "Each stretch is slowed by the weather forecast for the hour the shipment reaches it, so a delay early in the trip moves every later stretch into different weather.",
                "road_speed": "Speed loss in rain, fog and snow follows the ranges published by the US Federal Highway Administration road weather programme; the larger figure is used for the latest arrival.",
                "driver_hours": "One driver: a 30 minute break every 4.5 hours and an 8 hour halt after 10 hours of driving. Two drivers: a 20 minute break every 5 hours. No stop is planned in the last two hours before the destination.",
                "limits": "Traffic, tolls, loading time and road closures are not modelled.",
            },
        }

    return await _shipment_cache.get_or_set(key, load)


def brief(result: dict[str, Any], index: int = 0) -> dict[str, Any]:
    route = result["routes"][index]
    return {
        "from": result["origin"]["name"], "to": result["destination"]["name"], "mode": result["mode_label"], "vehicle": result["vehicle_label"], "cargo": result["cargo_label"],
        "route": route["summary"], "distance_km": route["distance_km"], "depart": route["depart"], "arrive": route["arrive"], "arrive_latest": route["arrive_latest"],
        "duration_min": route["duration_min"], "weather_delay_min": route["delay_min"], "weather_delay_worst_min": route["delay_worst_min"], "rest_min": route["rest_min"],
        "verdict": route["verdict"]["label"], "reasons": route["verdict"]["reasons"], "risk": route["risk"]["label"],
        "hazards": [{k: h.get(k) for k in ("kind", "detail", "from_km", "to_km", "from_eta", "to_eta", "near")} for h in route["hazards"][:6]],
        "official_warnings": [{k: w[k] for k in ("event", "severity", "from_km", "to_km", "active_on_arrival")} for w in route["warnings"][:5]],
        "cyclones": route["cyclones"], "cargo_status": route["cargo"]["status"], "cargo_notes": route["cargo"]["notes"],
        "cargo_metrics": route["cargo"]["metrics"], "actions": route["actions"], "best_departure": route["best_departure"],
        "summary": route["narrative"], "delay_by_cause": [{k: row[k] for k in ("label", "km", "hours", "severity", "delay_min", "worst")} for row in route["breakdown"]],
        "confidence": route["confidence"], "extremes": route.get("extremes"), "driver_rest": route["rests"],
        "stages": [{k: st[k] for k in ("from", "to", "from_km", "to_km", "from_eta", "to_eta", "temp_min", "temp_max", "rain_mm", "gust_max", "vis_min", "wave_max", "sky", "worst")} for st in route.get("stages") or []],
        "model_agreement": [{k: c[k] for k in ("where", "place", "date", "label", "score", "rain_agreement")} for c in route.get("model_check") or []],
        "other_crew_option": route.get("other_crew"), "top_dispatch_times": route.get("top_departures"),
        "alternatives": [{"route": r["summary"], "distance_km": r["distance_km"], "duration_min": r["duration_min"], "verdict": r["verdict"]["label"]} for i, r in enumerate(result["routes"]) if i != index],
    }


def localise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: localise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [localise(v) for v in value]
    if isinstance(value, str) and len(value) >= 19 and value[4:5] == "-" and value[10:11] == "T":
        try:
            return datetime.fromisoformat(value).astimezone(IST).strftime("%a %d %b %H:%M")
        except ValueError:
            return value
    return value


ANALYSIS_PROMPT = (
    "You are the senior logistics meteorologist at WeatherGPT. A dispatcher has to decide about one shipment. Write a thorough briefing in English from the JSON facts below. "
    "Use only those facts: never invent a number, place, time or warning, and never contradict the verdict. All times in the JSON are already India Standard Time; write them as given. "
    "Use markdown with exactly these section headings, each starting with '### ': Bottom line; Timeline; Weather along the route; Schedule risk; Cargo; Decision and actions; What could change. "
    "Under Timeline give dispatch, each rest stop and arrival as bullets. Under Weather along the route go stage by stage with the numbers (temperature, rain, gusts, visibility or waves) and say where and when each hazard is met. "
    "Under Schedule risk explain the expected and worst-case delay, what causes it, and how confident the forecast is, including model agreement. "
    "Under Decision and actions give numbered, specific steps for the dispatcher and the driver or crew, and compare the best alternative dispatch times if any are given. "
    "Under What could change say which forecast elements would alter the decision and when to re-check. Write 450 to 700 words in plain, formal language. No tables, no greeting, no closing remarks."
)


async def analysis(request: dict[str, Any], index: int = 0) -> dict[str, Any]:
    result = await shipment(request)
    index = max(0, min(index, len(result["routes"]) - 1))
    facts = localise(brief(result, index))
    key = hashlib.sha1(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()

    async def load() -> dict[str, Any]:
        text, label = await providers.complete(ANALYSIS_PROMPT, json.dumps(facts, ensure_ascii=False, default=str))
        return {"text": text.strip(), "model": label}

    try:
        return await _analysis_cache.get_or_set(key, load)
    except Exception as exc:
        log.info("analysis unavailable: %s", str(exc)[:160])
        return {"text": "\n\n".join(result["routes"][index]["narrative"]), "model": None}


async def fleet(items: list[dict[str, Any]]) -> dict[str, Any]:
    if len(items) > MAX_FLEET:
        raise TripError(f"At most {MAX_FLEET} shipments per request")
    gate = asyncio.Semaphore(3)

    async def one(item: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            try:
                result = await shipment(item, detail=False)
            except TripError as exc:
                return {"ref": item.get("ref"), "ok": False, "error": str(exc)}
            except Exception as exc:
                log.warning("fleet item failed: %s", exc)
                return {"ref": item.get("ref"), "ok": False, "error": "Weather or routing data unavailable right now"}
            route = result["routes"][0]
            worst = max(route["hazards"], key=lambda h: h["level"], default=None)
            return {
                "ref": item.get("ref"), "ok": True, "origin": result["origin"], "destination": result["destination"], "mode": result["mode"], "mode_label": result["mode_label"],
                "vehicle_label": result["vehicle_label"], "cargo_label": result["cargo_label"], "distance_km": route["distance_km"], "depart": route["depart"], "arrive": route["arrive"],
                "arrive_latest": route["arrive_latest"], "duration_min": route["duration_min"], "delay_min": route["delay_min"], "verdict": route["verdict"], "risk": route["risk"],
                "cargo_status": route["cargo"]["status"], "worst": {k: worst.get(k) for k in ("kind", "detail", "from_km", "to_km", "near")} if worst else None,
                "warnings": len([w for w in route["warnings"] if w["active_on_arrival"]]), "cyclones": len(route["cyclones"]), "best_departure": route["best_departure"],
                "track": route["points"],
            }

    rows = await asyncio.gather(*(one(item) for item in items))
    done = [r for r in rows if r["ok"]]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "shipments": rows,
        "summary": {"total": len(rows), "go": sum(1 for r in done if r["verdict"]["code"] == "go"), "caution": sum(1 for r in done if r["verdict"]["code"] == "caution"), "hold": sum(1 for r in done if r["verdict"]["code"] == "hold"), "failed": len(rows) - len(done), "delay_min": sum(r["delay_min"] for r in done)},
    }


SITE_RULES: dict[str, dict[str, Any]] = {
    "port": {"gust_stop": 72, "gust_watch": 50, "vis_stop": 200, "vis_watch": 1000, "rain_stop": 20, "wave_stop": 3.0, "heat": None},
    "airport": {"gust_stop": 65, "gust_watch": 45, "vis_stop": 200, "vis_watch": 800, "rain_stop": 30, "wave_stop": None, "heat": None},
    "hub": {"gust_stop": 60, "gust_watch": 45, "vis_stop": None, "vis_watch": None, "rain_stop": 7.6, "wave_stop": None, "heat": 41},
}
SITE_WORDS = {
    "port": {"gust": "crane and yard work stops", "vis": "pilotage and vessel movement restricted", "rain": "yard and gate work slows", "thunder": "crane and deck work stops for lightning", "wave": "pilot boarding and berthing difficult"},
    "airport": {"gust": "ramp handling and turnarounds slow", "vis": "low-visibility procedures; departures and arrivals held", "rain": "ramp handling slows", "thunder": "ramp closed for lightning"},
    "hub": {"gust": "outdoor loading unsafe", "rain": "dock loading of uncovered cargo stops", "thunder": "outdoor loading stops for lightning", "heat": "manual loading should move to cooler hours"},
}


def site_days(kind: str, land: dict[str, Any], marine: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    rule = SITE_RULES[kind]
    words = SITE_WORDS[kind]
    hourly = land["hourly"]
    waves = (marine or {}).get("hourly", {}).get("wave_height") or []
    days: dict[str, dict[str, Any]] = {}
    for n, stamp in enumerate(hourly["time"]):
        moment = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        if moment < now - timedelta(hours=1):
            continue
        local = moment.astimezone(IST)
        day = days.setdefault(local.strftime("%Y-%m-%d"), {"date": local.strftime("%Y-%m-%d"), "lost": 0, "slow": 0, "rain_mm": 0.0, "gust_max": 0.0, "vis_min": None, "feels_max": None, "wave_max": None, "why": {}, "hours": 0})
        rain = hourly["precipitation"][n] or 0
        gust = hourly["wind_gusts_10m"][n] or 0
        vis = hourly["visibility"][n]
        feels = hourly["apparent_temperature"][n]
        code = hourly["weather_code"][n] or 0
        wave = waves[n] if n < len(waves) else None
        day["hours"] += 1
        day["rain_mm"] += rain
        day["gust_max"] = max(day["gust_max"], gust)
        if vis is not None:
            day["vis_min"] = vis if day["vis_min"] is None else min(day["vis_min"], vis)
        if feels is not None:
            day["feels_max"] = feels if day["feels_max"] is None else max(day["feels_max"], feels)
        if wave is not None:
            day["wave_max"] = wave if day["wave_max"] is None else max(day["wave_max"], wave)
        stops = []
        if gust >= rule["gust_stop"]:
            stops.append("gust")
        if rule["vis_stop"] is not None and vis is not None and vis < rule["vis_stop"]:
            stops.append("vis")
        if rain >= rule["rain_stop"]:
            stops.append("rain")
        if code >= 95:
            stops.append("thunder")
        if rule["wave_stop"] is not None and wave is not None and wave >= rule["wave_stop"]:
            stops.append("wave")
        slows = []
        if not stops:
            if gust >= rule["gust_watch"]:
                slows.append("gust")
            if rule["vis_watch"] is not None and vis is not None and vis < rule["vis_watch"]:
                slows.append("vis")
            if rule["heat"] is not None and feels is not None and feels >= rule["heat"]:
                slows.append("heat")
            if rain >= 2.5 and kind != "airport":
                slows.append("rain")
        if stops:
            day["lost"] += 1
        elif slows:
            day["slow"] += 1
        for key in stops + slows:
            day["why"][key] = day["why"].get(key, 0) + 1
    out = []
    for day in list(days.values())[:5]:
        rain_total = round(day["rain_mm"], 1)
        level = 0
        if day["slow"] >= 2 or day["lost"] >= 1:
            level = 1
        if day["lost"] >= 3 or rain_total >= 64.5:
            level = 2
        if day["lost"] >= 8 or rain_total >= 115.6:
            level = 3
        reasons = [f"{words[k]} ({hours} h)" for k, hours in sorted(day["why"].items(), key=lambda kv: -kv[1]) if k in words]
        if rain_total >= 64.5:
            reasons.insert(0, f"{rain_total:g} mm of rain in the day; flooding of yards and approach roads possible")
        out.append({
            "date": day["date"], "level": level, "status": ["Normal", "Watch", "Disrupted", "Shut down likely"][level], "lost_hours": day["lost"], "slow_hours": day["slow"], "hours": day["hours"],
            "rain_mm": rain_total, "gust_max": round(day["gust_max"]), "vis_min": None if day["vis_min"] is None else round(day["vis_min"]),
            "feels_max": None if day["feels_max"] is None else round(day["feels_max"]), "wave_max": None if day["wave_max"] is None else round(day["wave_max"], 1), "reasons": reasons[:4],
        })
    return out


def _site_list(kind: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if kind in ("all", "port"):
        out += [{"id": f"port:{p['id']}", "kind": "port", "name": p["name"], "area": p["state"], "lat": p["lat"], "lon": p["lon"], "sea": SEA_CHAIN[p["node"]][:2] if p["node"] >= 0 else (p["lat"], p["lon"] + 0.15)} for p in PORTS]
    if kind in ("all", "airport"):
        out += [{"id": f"airport:{a['icao']}", "kind": "airport", "name": a["name"], "area": a.get("city"), "lat": a["lat"], "lon": a["lon"], "code": a.get("iata") or a["icao"]} for a in trips.airports() if a.get("size") == "large"]
    if kind in ("all", "hub"):
        out += [{"id": f"hub:{h['id']}", "kind": "hub", "name": h["name"], "area": h["city"], "lat": h["lat"], "lon": h["lon"]} for h in HUBS]
    return out


async def _sites(sites: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    land = await series_for([(s["lat"], s["lon"]) for s in sites], 6, hourly=SITE_HOURLY)
    ports = [s for s in sites if s["kind"] == "port"]
    marine = await series_for([s["sea"] for s in ports], 6, weather.MARINE_URL, "wave_height") if ports else []
    sea_by_id = {s["id"]: m for s, m in zip(ports, marine)}
    try:
        board = (await fieldmap.warnings())["warnings"]
    except Exception:
        board = []
    try:
        storms = (await cyclones.storms())["active"]
    except Exception:
        storms = []
    out = []
    for site, series in zip(sites, land):
        days = site_days(site["kind"], series, sea_by_id.get(site["id"]), now)
        current = trips._at(series, now) or {}
        official = [
            {"event": w["event"], "severity": w["severity"], "headline": w["headline"], "issuer": w["issuer"], "expires": w["expires"]}
            for w in board
            if any(cyclones.inside((site["lat"], site["lon"]), ring) for ring in w["rings"])
        ]
        threat = None
        for storm in storms:
            try:
                hit = cyclones.impact(storm, site["lat"], site["lon"])
            except Exception:
                continue
            near = (hit.get("closest") or {}).get("km")
            if near is not None and (near <= 400 or hit.get("in_cone")) and (threat is None or near < threat["closest_km"]):
                threat = {"name": storm.get("name"), "closest_km": round(near), "closest_time": (hit.get("closest") or {}).get("time"), "in_cone": hit.get("in_cone"), "stage": hit.get("stage")}
        level = max((d["level"] for d in days[:2]), default=0)
        if threat and (threat.get("stage") or threat["closest_km"] <= 200):
            level = 3
        elif official and level == 0:
            level = 1
        out.append({
            "id": site["id"], "kind": site["kind"], "name": site["name"], "area": site.get("area"), "code": site.get("code"), "lat": site["lat"], "lon": site["lon"],
            "level": level, "status": ["Normal", "Watch", "Disrupted", "Shut down likely"][level],
            "now": {"temp": current.get("temperature_2m"), "feels": current.get("apparent_temperature"), "rain_mmh": current.get("precipitation"), "gust": current.get("wind_gusts_10m"), "visibility": current.get("visibility"), "label": describe(current.get("weather_code") or 0)["label"]},
            "days": days, "warnings": official[:4], "cyclone": threat,
        })
    out.sort(key=lambda s: (-s["level"], -sum(d["lost_hours"] for d in s["days"][:2]), s["name"]))
    return {
        "generated_at": now.isoformat(), "sites": out,
        "summary": {"total": len(out), "normal": sum(1 for s in out if s["level"] == 0), "watch": sum(1 for s in out if s["level"] == 1), "disrupted": sum(1 for s in out if s["level"] >= 2)},
        "rules": {
            "port": "Yard cranes stop at gusts of 72 km/h and ship-to-shore cranes near 80 km/h; work also stops for lightning, visibility under 200 m, rain of 20 mm/h and waves of 3 m at the approach.",
            "airport": "Disruption is counted for visibility under 200 m, thunderstorms, gusts of 65 km/h and rain of 30 mm/h; visibility under 800 m and gusts of 45 km/h count as slow hours.",
            "hub": "Outdoor loading stops for lightning, rain of 7.6 mm/h and gusts of 60 km/h; a feels-like temperature of 41 °C counts as slow hours. A day with 64.5 mm of rain is flagged for flooding.",
        },
    }


async def facilities(kind: str = "all") -> dict[str, Any]:
    if kind not in ("all", "port", "airport", "hub"):
        raise TripError("kind must be all, port, airport or hub")
    return await _site_cache.get_or_set(kind, lambda: _sites(_site_list(kind)))


async def custom_sites(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise TripError("Send at least one site")
    if len(items) > MAX_SITES:
        raise TripError(f"At most {MAX_SITES} sites per request")
    sites = []
    for n, item in enumerate(items):
        kind = item.get("kind") or "hub"
        if kind not in SITE_RULES:
            raise TripError("Site kind must be port, airport or hub")
        place = await resolve(item)
        sites.append({"id": str(item.get("ref") or f"site:{n}"), "kind": kind, "name": item.get("name") or place["name"], "area": place.get("state"), "lat": place["lat"], "lon": place["lon"], "sea": (place["lat"], place["lon"])})
    key = hashlib.sha1(json.dumps([[s["id"], s["kind"], round(s["lat"], 2), round(s["lon"], 2)] for s in sites]).encode()).hexdigest()
    return await _site_cache.get_or_set(key, lambda: _sites(sites))


def _lane_id(a: str, b: str) -> str:
    return f"{a.lower()}-{b.lower()}"


def _pack(route: Route, limit: int = 500) -> dict[str, Any]:
    step = max(1, len(route.coords) // limit)
    keep = list(range(0, len(route.coords), step))
    if keep[-1] != len(route.coords) - 1:
        keep.append(len(route.coords) - 1)
    return {"coords": [[round(route.coords[i][0], 4), round(route.coords[i][1], 4)] for i in keep], "m": [round(route.cum_m[i]) for i in keep], "s": [round(route.cum_s[i]) for i in keep], "summary": route.summary}


def _unpack(raw: dict[str, Any]) -> Route:
    return Route([(a, b) for a, b in raw["coords"]], [float(m) for m in raw["m"]], [float(s) for s in raw["s"]], raw.get("summary") or "", MODES["road"]["source"])


async def lane_routes() -> dict[str, Route]:
    async with _lane_lock:
        if len(_lane_routes) == len(LANES):
            return _lane_routes
        stored: dict[str, Any] = {}
        if LANE_CACHE.exists():
            try:
                stored = json.loads(LANE_CACHE.read_text(encoding="utf-8"))
            except ValueError:
                stored = {}
        changed = False
        for a, b in LANES:
            key = _lane_id(a, b)
            if key in _lane_routes:
                continue
            if key in stored:
                _lane_routes[key] = _unpack(stored[key])
                continue
            try:
                route = (await trips._osrm("car", [CITIES[a], CITIES[b]], 1.0, alternatives=False))[0]
            except Exception as exc:
                log.warning("lane %s unavailable: %s", key, exc)
                continue
            stored[key] = _pack(route)
            _lane_routes[key] = _unpack(stored[key])
            changed = True
            await asyncio.sleep(0.4)
        if changed:
            try:
                LANE_CACHE.parent.mkdir(parents=True, exist_ok=True)
                LANE_CACHE.write_text(json.dumps(stored), encoding="utf-8")
            except OSError as exc:
                log.info("lane cache not written: %s", exc)
        return _lane_routes


async def network() -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        routes = await lane_routes()
        if not routes:
            raise TripError("Road routing is unavailable right now")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        factor = VEHICLES["hcv"]["factor"]
        spec = {"mode": "road", "vehicle": "hcv", "crew": 2, "high_sided": False, "open_body": True}
        prepared = []
        for a, b in LANES:
            base = routes.get(_lane_id(a, b))
            if base is None:
                continue
            route = Route(base.coords, base.cum_m, [s * factor for s in base.cum_s], base.summary, base.source)
            prepared.append((a, b, route, _pick(route, 10)))
        flat = [route.coords[i] for _, _, route, picks in prepared for i in picks]
        series = await series_for(flat, 4, hourly=LANE_HOURLY, size=50)
        try:
            board = (await fieldmap.warnings())["warnings"]
        except Exception:
            board = []
        lanes = []
        cursor = 0
        for a, b, route, picks in prepared:
            land = series[cursor:cursor + len(picks)]
            cursor += len(picks)
            run = simulate(route, picks, land, None, now, spec)
            outlook = []
            for hours in (0, 6, 12, 24, 36):
                trial = run if hours == 0 else simulate(route, picks, land, None, now + timedelta(hours=hours), spec)
                if trial["coverage"] < 0.9:
                    break
                outlook.append({"depart": (now + timedelta(hours=hours)).isoformat(), "hours": hours, "delay_min": round(trial["delay_s"] / 60), "score": trial["score"], "risk": risk_label(trial["score"])})
            worst_point = max(run["points"], key=lambda p: p["level"])
            worst = max(worst_point["hazards"], key=lambda h: h["level"], default=None)
            path = _thin_path(route, 80)
            crossing = [w for w in board if w["rings"] and any(cyclones.inside((p[1], p[2]), ring) for p in path for ring in w["rings"])]
            lanes.append({
                "id": _lane_id(a, b), "name": f"{a} – {b}", "from": {"name": a, "lat": CITIES[a][0], "lon": CITIES[a][1]}, "to": {"name": b, "lat": CITIES[b][0], "lon": CITIES[b][1]},
                "via": route.summary, "distance_km": round(route.meters / 1000), "base_min": round(route.seconds / 60), "duration_min": round((run["arrive"] - now).total_seconds() / 60),
                "delay_min": round(run["delay_s"] / 60), "delay_worst_min": round(run["delay_worst_s"] / 60), "risk": {"score": run["score"], "label": risk_label(run["score"])}, "level": min(3, int(run["score"])),
                "worst": {"kind": worst["kind"], "detail": worst["detail"], "km": worst_point["km"]} if worst else None,
                "warnings": [{"event": w["event"], "severity": w["severity"]} for w in crossing[:4]], "warning_count": len(crossing),
                "outlook": outlook, "segments": [{"lat": p["lat"], "lon": p["lon"], "level": p["level"]} for p in run["points"]],
                "geometry": trips._simplify(route.coords, 160),
            })
        lanes.sort(key=lambda lane: (-lane["risk"]["score"], -lane["delay_min"], lane["name"]))
        return {
            "generated_at": now.isoformat(), "lanes": lanes, "vehicle": VEHICLES["hcv"]["label"],
            "summary": {"total": len(lanes), "clear": sum(1 for l in lanes if l["level"] == 0), "affected": sum(1 for l in lanes if l["level"] >= 1), "delay_min": sum(l["delay_min"] for l in lanes), "worst": lanes[0]["name"] if lanes and lanes[0]["level"] >= 1 else None},
        }

    return await _network_cache.get_or_set("india", load)
