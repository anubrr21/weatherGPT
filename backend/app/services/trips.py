import asyncio
import hashlib
import heapq
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.services import alerts as alert_service
from app.services import weather
from app.services.http import TTLCache, client, get_retry
from app.services.wmo import describe

log = logging.getLogger("weathergpt.trips")

DATA = Path(__file__).resolve().parent.parent / "data"
RAIL = Path(__file__).resolve().parent.parent.parent / "data" / "rail"
OSRM = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/{a};{b}"
UA = {"User-Agent": "WeatherGPT/0.1"}
HOURLY = "temperature_2m,apparent_temperature,precipitation,precipitation_probability,weather_code,wind_gusts_10m,visibility,is_day,cape,wind_speed_250hPa,wind_direction_250hPa"

MODES: dict[str, dict[str, Any]] = {
    "car": {"label": "Car", "router": "car", "factor": 1.0, "source": "OSRM road routing on OpenStreetMap"},
    "bus": {"label": "Bus", "router": "car", "factor": 1.3, "source": "OSRM road routing on OpenStreetMap, bus time about 30% slower than car"},
    "bike": {"label": "Two-wheeler", "router": "car", "factor": 1.12, "source": "OSRM road routing on OpenStreetMap, two-wheeler time about 12% slower than car"},
    "train": {"label": "Train", "router": "rail", "factor": 1.0, "source": "OpenStreetMap Indian railway network, time at a typical 55 km/h express average"},
    "flight": {"label": "Flight", "router": "air", "factor": 1.0, "source": "Great-circle route between the nearest scheduled airports, 780 km/h cruise adjusted for jet-level winds"},
    "trek": {"label": "Trek / walk", "router": "foot", "factor": 1.0, "source": "OSRM foot routing on OpenStreetMap"},
}
LEVELS = ["Low", "Moderate", "High", "Severe"]

_route_cache = TTLCache(ttl_s=3600)
_weather_cache = TTLCache(ttl_s=600)
_plan_cache = TTLCache(ttl_s=600)


class TripError(Exception):
    pass


@dataclass
class Route:
    coords: list[tuple[float, float]]
    cum_m: list[float]
    cum_s: list[float]
    summary: str
    source: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def meters(self) -> float:
        return self.cum_m[-1] if self.cum_m else 0.0

    @property
    def seconds(self) -> float:
        return self.cum_s[-1] if self.cum_s else 0.0


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, h)))


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def cumulative(coords: list[tuple[float, float]]) -> list[float]:
    out = [0.0]
    for a, b in zip(coords, coords[1:]):
        out.append(out[-1] + haversine(a, b))
    return out


async def _osrm(profile: str, a: tuple[float, float], b: tuple[float, float], factor: float, alternatives: bool) -> list[Route]:
    url = OSRM.format(profile=profile, a=f"{a[1]:.5f},{a[0]:.5f}", b=f"{b[1]:.5f},{b[0]:.5f}")
    params = {"overview": "full", "geometries": "geojson", "annotations": "duration,distance", "alternatives": "3" if alternatives else "false"}
    response = await get_retry(url, params=params, headers=UA, timeout=45)
    data = response.json() if response.status_code == 200 else {}
    if data.get("code") != "Ok" or not data.get("routes"):
        raise TripError(f"No {profile} route found between these places")
    routes = []
    for raw in data["routes"][:3]:
        coords = [(lat, lon) for lon, lat in raw["geometry"]["coordinates"]]
        durations = [d for leg in raw["legs"] for d in leg["annotation"]["duration"]]
        distances = [d for leg in raw["legs"] for d in leg["annotation"]["distance"]]
        cum_m, cum_s = [0.0], [0.0]
        for d, s in zip(distances, durations):
            cum_m.append(cum_m[-1] + d)
            cum_s.append(cum_s[-1] + s * factor)
        n = min(len(coords), len(cum_m))
        summary = " · ".join(leg.get("summary", "") for leg in raw["legs"] if leg.get("summary")) or "Main route"
        routes.append(Route(coords[:n], cum_m[:n], cum_s[:n], summary, ""))
    return routes


@lru_cache(maxsize=1)
def _rail() -> dict[str, Any] | None:
    path = RAIL / "india_rail.npz"
    if not path.exists():
        return None
    data = np.load(path)
    coords = data["coords"].astype(np.float64)
    adjacency: list[list[tuple[int, float]]] = [[] for _ in range(len(coords))]
    for a, b, m in zip(data["src"].tolist(), data["dst"].tolist(), data["meters"].tolist()):
        adjacency[a].append((b, m))
        adjacency[b].append((a, m))
    names = json.loads((RAIL / "stations.json").read_text(encoding="utf-8"))
    return {"coords": coords, "adj": adjacency, "stations": data["station_xy"].astype(np.float64), "names": names}


def _nearest(points: np.ndarray, lat: float, lon: float) -> tuple[int, float]:
    d = (points[:, 0] - lat) ** 2 + ((points[:, 1] - lon) * math.cos(math.radians(lat))) ** 2
    i = int(np.argmin(d))
    return i, haversine((lat, lon), (float(points[i, 0]), float(points[i, 1])))


def _dijkstra(adj: list[list[tuple[int, float]]], start: int, goal: int, coords: np.ndarray) -> list[int]:
    target = (coords[goal, 0], coords[goal, 1])
    best = {start: 0.0}
    parent = {start: -1}
    queue = [(0.0, 0.0, start)]
    while queue:
        _, g, node = heapq.heappop(queue)
        if node == goal:
            path = []
            while node != -1:
                path.append(node)
                node = parent[node]
            return path[::-1]
        if g > best.get(node, math.inf):
            continue
        for nxt, m in adj[node]:
            cost = g + m
            if cost < best.get(nxt, math.inf):
                best[nxt] = cost
                parent[nxt] = node
                h = haversine((coords[nxt, 0], coords[nxt, 1]), target) * 0.95
                heapq.heappush(queue, (cost + h, cost, nxt))
    return []


def _rail_route(a: tuple[float, float], b: tuple[float, float]) -> Route:
    graph = _rail()
    if graph is None:
        raise TripError("The Indian railway network is still being built on this server; try road or flight")
    sa, da = _nearest(graph["stations"], *a)
    sb, db = _nearest(graph["stations"], *b)
    if da > 40000 or db > 40000:
        raise TripError("No railway station within 40 km of one of these places")
    na, _ = _nearest(graph["coords"], *graph["stations"][sa])
    nb, _ = _nearest(graph["coords"], *graph["stations"][sb])
    path = _dijkstra(graph["adj"], na, nb, graph["coords"])
    if len(path) < 2:
        raise TripError(f"No continuous railway line found between {graph['names'][sa]} and {graph['names'][sb]} in OpenStreetMap")
    coords = [(float(graph["coords"][i, 0]), float(graph["coords"][i, 1])) for i in path]
    cum_m = cumulative(coords)
    speed = 55 / 3.6
    cum_s = [m / speed for m in cum_m]
    extra = {
        "from_station": {"name": graph["names"][sa], "lat": float(graph["stations"][sa, 0]), "lon": float(graph["stations"][sa, 1]), "km_from_origin": round(da / 1000, 1)},
        "to_station": {"name": graph["names"][sb], "lat": float(graph["stations"][sb, 0]), "lon": float(graph["stations"][sb, 1]), "km_from_destination": round(db / 1000, 1)},
    }
    return Route(coords, cum_m, cum_s, f"{graph['names'][sa]} → {graph['names'][sb]}", "", extra)


@lru_cache(maxsize=1)
def airports() -> list[dict[str, Any]]:
    return json.loads((DATA / "india_airports.json").read_text(encoding="utf-8"))


def nearest_airport(lat: float, lon: float) -> tuple[dict[str, Any], float]:
    ranked = sorted(airports(), key=lambda x: haversine((lat, lon), (x["lat"], x["lon"])) * (0.8 if x["size"] == "large" else 1.0))
    best = ranked[0]
    return best, haversine((lat, lon), (best["lat"], best["lon"]))


def _great_circle(a: tuple[float, float], b: tuple[float, float], steps: int) -> list[tuple[float, float]]:
    p1, l1, p2, l2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = haversine(a, b) / 6371000
    if d == 0:
        return [a, b]
    out = []
    for i in range(steps + 1):
        f = i / steps
        A, B = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
        x = A * math.cos(p1) * math.cos(l1) + B * math.cos(p2) * math.cos(l2)
        y = A * math.cos(p1) * math.sin(l1) + B * math.cos(p2) * math.sin(l2)
        z = A * math.sin(p1) + B * math.sin(p2)
        out.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return out


def _air_route(a: tuple[float, float], b: tuple[float, float]) -> Route:
    dep, dep_m = nearest_airport(*a)
    arr, arr_m = nearest_airport(*b)
    if dep["icao"] == arr["icao"]:
        raise TripError(f"Both places are closest to {dep['name']}; flying makes no sense for this trip")
    coords = _great_circle((dep["lat"], dep["lon"]), (arr["lat"], arr["lon"]), 60)
    cum_m = cumulative(coords)
    total = cum_m[-1]
    cruise = 780 / 3.6
    cum_s = [25 * 60 + m / cruise for m in cum_m]
    cum_s[0] = 0.0
    cum_s[-1] += 15 * 60
    extra = {"from_airport": dep | {"km_from_origin": round(dep_m / 1000, 1)}, "to_airport": arr | {"km_from_destination": round(arr_m / 1000, 1)}, "great_circle_km": round(total / 1000)}
    return Route(coords, cum_m, cum_s, f"{dep.get('iata') or dep['icao']} → {arr.get('iata') or arr['icao']}", "", extra)


async def routes_for(mode: str, a: tuple[float, float], b: tuple[float, float]) -> list[Route]:
    spec = MODES[mode]
    key = f"{mode}:{a[0]:.3f},{a[1]:.3f}:{b[0]:.3f},{b[1]:.3f}"

    async def load() -> list[Route]:
        if spec["router"] == "car":
            found = await _osrm("car", a, b, spec["factor"], alternatives=True)
        elif spec["router"] == "foot":
            found = await _osrm("foot", a, b, 1.0, alternatives=False)
        elif spec["router"] == "rail":
            found = [await asyncio.to_thread(_rail_route, a, b)]
        else:
            found = [_air_route(a, b)]
        for route in found:
            route.source = spec["source"]
        return found

    return await _route_cache.get_or_set(key, load)


def sample(route: Route, max_points: int = 32) -> list[int]:
    total = route.meters
    step = max(8000.0, total / max_points)
    picks, next_at = [0], step
    for i, m in enumerate(route.cum_m):
        if m >= next_at:
            picks.append(i)
            next_at = m + step
    if picks[-1] != len(route.cum_m) - 1:
        picks.append(len(route.cum_m) - 1)
    return picks


async def _weather_batch(points: list[tuple[float, float]], days: int) -> list[dict[str, Any]]:
    key = hashlib.sha1(json.dumps([[round(p[0], 2), round(p[1], 2)] for p in points] + [days]).encode()).hexdigest()

    async def load() -> list[dict[str, Any]]:
        response = await client().get(
            weather.FORECAST_URL,
            params={
                "latitude": ",".join(f"{p[0]:.3f}" for p in points),
                "longitude": ",".join(f"{p[1]:.3f}" for p in points),
                "hourly": HOURLY,
                "forecast_days": days,
                "timezone": "GMT",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else [data]

    return await _weather_cache.get_or_set(key, load)


async def weather_along(points: list[tuple[float, float]], days: int) -> list[dict[str, Any]]:
    chunks = [points[i:i + 8] for i in range(0, len(points), 8)]
    results = await asyncio.gather(*(_weather_batch(chunk, days) for chunk in chunks))
    return [item for batch in results for item in batch]


def _at(series: dict[str, Any], moment: datetime) -> dict[str, Any] | None:
    times = series["hourly"]["time"]
    start = datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc)
    index = round((moment - start).total_seconds() / 3600)
    if index < 0 or index >= len(times):
        return None
    hourly = series["hourly"]
    return {k: hourly[k][index] for k in hourly if k != "time"} | {"time": times[index], "elevation": series.get("elevation")}


def assess(w: dict[str, Any], mode: str, phase: str = "ground") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(kind: str, level: float, detail: str) -> None:
        out.append({"kind": kind, "level": level, "detail": detail})

    rain = w.get("precipitation") or 0
    code = w.get("weather_code") or 0
    gust = w.get("wind_gusts_10m") or 0
    vis = w.get("visibility")
    feels = w.get("apparent_temperature")
    temp = w.get("temperature_2m")
    road = mode in ("car", "bus", "bike")
    exposed = mode in ("bike", "trek")
    if mode == "flight" and phase == "cruise":
        cape = w.get("cape") or 0
        if code >= 95 or cape >= 2500:
            add("convection", 2 if code >= 95 else 1, f"Deep convection likely (CAPE {cape:.0f} J/kg); expect turbulence and deviations")
        jet = w.get("wind_speed_250hPa") or 0
        if jet >= 180:
            add("jet", 1, f"Jet stream at cruise level, {jet:.0f} km/h; clear-air turbulence possible")
        return out
    if code >= 95:
        add("thunder", 3 if code >= 96 else 2.5, "Thunderstorm with lightning" + (" and hail" if code >= 96 else ""))
    elif code in (71, 73, 75, 77, 85, 86) and road:
        add("snow", 3, "Snowfall; hill roads can close")
    if rain >= 7.6:
        add("rain", 2 if not exposed else 2.5, f"Heavy rain, {rain:.1f} mm/h; waterlogging and poor visibility")
    elif rain >= 2.5:
        add("rain", 1 if not exposed else 1.5, f"Moderate rain, {rain:.1f} mm/h")
    elif rain >= 0.5 and exposed:
        add("rain", 0.5, f"Light rain, {rain:.1f} mm/h")
    if vis is not None:
        if vis < 200:
            add("fog", 3 if road or mode == "flight" else 2, f"Dense fog, visibility about {vis:.0f} m")
        elif vis < 1000 and mode != "trek":
            add("fog", 1.5 if road else 1, f"Fog or mist, visibility about {vis:.0f} m")
    if gust >= (40 if exposed else 60):
        add("wind", 2 if gust >= 70 else 1.5, f"Strong gusts up to {gust:.0f} km/h")
    if feels is not None and feels >= 41 and mode != "flight":
        add("heat", (2 if feels >= 46 else 1.5) if exposed or mode == "bus" else 0.5, f"Feels like {feels:.0f}°C")
    if temp is not None and temp <= 5 and (exposed or road):
        add("cold", 2 if temp <= 0 else 1, f"Cold, {temp:.0f}°C" + ("; ice possible on roads" if temp <= 0 and road else ""))
    if mode == "train":
        out = [h | {"level": min(h["level"], 2 if h["kind"] in ("fog", "thunder") else 1)} for h in out]
    return out


ADVICE = {
    "thunder": {"car": "Stay in the car if caught in lightning, away from trees; pull over safely if visibility collapses.", "bike": "Do not ride through lightning. Shelter in a building, not under trees or flyovers.", "trek": "Get off ridges and open ground before it arrives; avoid lone trees and water.", "bus": "Expect slow traffic and possible stoppages.", "train": "Lightning rarely stops trains, but expect signalling delays.", "flight": "Thunderstorms at the airport often cause holding or diversions."},
    "rain": {"car": "Drive slower, keep headlights on and avoid underpasses that flood.", "bike": "Wear rain gear, brake early, avoid painted lines and potholes hidden by water.", "trek": "Trails get slippery and streams can rise fast; carry waterproofs.", "bus": "Allow extra time for traffic.", "train": "Heavy rain can waterlog tracks and cause delays.", "flight": "Heavy rain can reduce runway capacity; allow for delays."},
    "fog": {"car": "Use low beam and fog lights, keep a long gap, avoid overtaking.", "bike": "Use low beam and reflective gear; consider waiting for the fog to lift.", "trek": "Stay on marked trails and keep your group together.", "bus": "Expect big delays on highways.", "train": "Dense fog is the most common cause of long train delays in North India.", "flight": "Low visibility can delay or divert flights; check with the airline."},
    "wind": {"car": "Hold the wheel firmly, especially on bridges and open stretches.", "bike": "Crosswinds can push you across lanes; slow down on bridges and open highways.", "trek": "Avoid exposed ridges and cliff edges.", "bus": "High-sided vehicles are affected most on open stretches.", "train": "Very strong winds can bring speed restrictions.", "flight": "Gusty winds cause bumpy take-offs and landings."},
    "heat": {"car": "Carry water and keep the AC serviced; avoid long stops in the sun.", "bike": "Ride early or late, cover your skin, drink water every 30 minutes.", "trek": "Start at dawn, rest in shade between 12 and 4 pm, carry electrolytes.", "bus": "Carry water; non-AC buses get very hot around midday."},
    "cold": {"car": "Watch for black ice on bridges and shaded hill roads.", "bike": "Wear layers and gloves; wind chill makes riding much colder.", "trek": "Carry warm layers; temperatures drop further with height."},
    "snow": {"car": "Hill roads may close; check with local authorities before leaving."},
    "convection": {"flight": "Storms en route often mean detours and a bumpy ride; keep seatbelts fastened."},
    "jet": {"flight": "A strong jet stream changes flight time and can cause clear-air turbulence."},
}


def advice(kind: str, mode: str) -> str:
    options = ADVICE.get(kind, {})
    return options.get(mode) or options.get("car") or ""


def risk_label(score: float) -> str:
    return LEVELS[min(3, int(score))]


def evaluate(route: Route, picks: list[int], series: list[dict[str, Any]], mode: str, depart: datetime) -> dict[str, Any]:
    points = []
    worst_by_point = []
    for n, (i, s) in enumerate(zip(picks, series)):
        eta = depart + timedelta(seconds=route.cum_s[i])
        w = _at(s, eta)
        phase = "ground"
        if mode == "flight":
            phase = "cruise" if 0 < n < len(picks) - 1 else "airport"
        hazards = assess(w, mode, phase) if w else []
        level = max((h["level"] for h in hazards), default=0.0)
        worst_by_point.append(level)
        points.append({
            "i": i, "lat": route.coords[i][0], "lon": route.coords[i][1], "km": round(route.cum_m[i] / 1000, 1), "eta": eta.isoformat(),
            "weather": None if not w else {
                "temp": w.get("temperature_2m"), "feels": w.get("apparent_temperature"), "rain_mmh": w.get("precipitation"),
                "rain_prob": w.get("precipitation_probability"), "code": w.get("weather_code"), "label": describe(w.get("weather_code") or 0)["label"],
                "gust": w.get("wind_gusts_10m"), "visibility": w.get("visibility"), "is_day": w.get("is_day"), "elevation": w.get("elevation"),
            },
            "hazards": hazards, "level": level,
        })
    covered = [p for p in points if p["weather"]]
    lengths = [(route.cum_m[picks[min(k + 1, len(picks) - 1)]] - route.cum_m[picks[max(k - 1, 0)]]) / 2 for k in range(len(picks))]
    total = sum(lengths) or 1.0
    score = sum(l * lv for l, lv in zip(lengths, worst_by_point)) / total + max(worst_by_point, default=0) * 0.5
    return {"points": points, "score": round(score, 3), "coverage": len(covered) / max(1, len(points)), "night": sum(1 for p in covered if p["weather"]["is_day"] == 0) / max(1, len(covered))}


def spans(points: list[dict[str, Any]], mode: str, places: dict[int, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in points:
        for h in p["hazards"]:
            last = next((s for s in reversed(out) if s["kind"] == h["kind"]), None)
            if last and last["_end"] == p["i_prev"]:
                last.update(to_km=p["km"], to_eta=p["eta"], _end=p["i"], level=max(last["level"], h["level"]))
                if h["level"] >= last["level"]:
                    last["detail"] = h["detail"]
            else:
                out.append({"kind": h["kind"], "level": h["level"], "detail": h["detail"], "from_km": p["km"], "to_km": p["km"], "from_eta": p["eta"], "to_eta": p["eta"], "_end": p["i"], "_start": p["i"]})
    for s in out:
        middle = (s["_start"] + s["_end"]) / 2
        near = min(places.items(), key=lambda kv: abs(kv[0] - middle))[1] if places else None
        s["near"] = near
        s["severity"] = risk_label(s["level"])
        s["advice"] = advice(s["kind"], mode)
        del s["_end"], s["_start"]
    return sorted(out, key=lambda s: (-s["level"], s["from_km"]))


async def _places(route: Route, picks: list[int]) -> dict[int, dict[str, Any]]:
    chosen = picks[:: max(1, len(picks) // 10)][:12]
    if picks[-1] not in chosen:
        chosen.append(picks[-1])

    async def one(i: int) -> tuple[int, dict[str, Any] | None]:
        try:
            return i, await weather.reverse_geocode(*route.coords[i])
        except Exception:
            return i, None

    found = await asyncio.gather(*(one(i) for i in chosen))
    return {i: p for i, p in found if p}


async def _airport_weather(extra: dict[str, Any]) -> None:
    for key in ("from_airport", "to_airport"):
        airport = extra.get(key)
        if airport:
            try:
                airport["metar"] = await weather.metar(airport["icao"])
            except Exception:
                airport["metar"] = None


def _simplify(coords: list[tuple[float, float]], limit: int = 700) -> list[list[float]]:
    step = max(1, len(coords) // limit)
    kept = coords[::step]
    if kept[-1] != coords[-1]:
        kept.append(coords[-1])
    return [[round(a, 5), round(b, 5)] for a, b in kept]


async def plan(origin: dict[str, Any], destination: dict[str, Any], mode: str, depart: datetime | None) -> dict[str, Any]:
    if mode not in MODES:
        raise TripError(f"Unknown mode {mode}")
    a, b = (origin["lat"], origin["lon"]), (destination["lat"], destination["lon"])
    if haversine(a, b) < 2000:
        raise TripError("Start and destination are the same place")
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    depart = (depart or now).astimezone(timezone.utc)
    if depart < now - timedelta(minutes=30):
        depart = now
    if depart > now + timedelta(days=6):
        raise TripError("Weather along the route is only reliable for trips starting in the next 6 days")
    key = f"{mode}:{a}:{b}:{depart:%Y%m%d%H}"

    async def load() -> dict[str, Any]:
        routes = await routes_for(mode, a, b)
        results = []
        for index, route in enumerate(routes):
            picks = sample(route)
            points = [route.coords[i] for i in picks]
            horizon = math.ceil(((depart - now).total_seconds() + route.seconds) / 86400) + 1
            series = await weather_along(points, max(2, min(7, horizon + 1)))
            chosen = evaluate(route, picks, series, mode, depart)
            for k, p in enumerate(chosen["points"]):
                p["i_prev"] = chosen["points"][k - 1]["i"] if k else -1
            departures = []
            for hours in range(0, 13):
                start = depart + timedelta(hours=hours)
                result = evaluate(route, picks, series, mode, start)
                if result["coverage"] < 0.9:
                    break
                departures.append({"depart": start.isoformat(), "score": result["score"], "risk": risk_label(result["score"]), "night": round(result["night"], 2)})
            best = min(departures, key=lambda d: (round(d["score"], 1), d["depart"])) if departures else None
            recommend = None
            if best and departures and best["depart"] != departures[0]["depart"] and best["score"] < departures[0]["score"] * 0.7 and departures[0]["score"] - best["score"] >= 0.3:
                recommend = best | {"why": f"Risk drops from {departures[0]['risk'].lower()} to {best['risk'].lower()} by leaving later"}
            places = await _places(route, picks) if index == 0 else {}
            names = {i: p.get("name") for i, p in places.items()}
            for p in chosen["points"]:
                if p["i"] in names:
                    p["place"] = names[p["i"]]
            active = []
            if places:
                official = await alert_service.official_alerts()
                seen = set()
                for i, place in places.items():
                    for alert in alert_service.alerts_for_place(official, place):
                        if alert.get("match") == "district" and alert["id"] not in seen:
                            seen.add(alert["id"])
                            active.append(alert | {"km": round(route.cum_m[i] / 1000), "near": place.get("name")})
            if mode == "flight":
                await _airport_weather(route.extra)
                track = bearing(route.coords[0], route.coords[-1])
                components = []
                for point, s in list(zip(chosen["points"], series))[1:-1]:
                    w = _at(s, datetime.fromisoformat(point["eta"]))
                    if w and w.get("wind_speed_250hPa") is not None and w.get("wind_direction_250hPa") is not None:
                        components.append(w["wind_speed_250hPa"] * math.cos(math.radians(w["wind_direction_250hPa"] + 180 - track)))
                if components:
                    tail = sum(components) / len(components)
                    adjusted = route.meters / 1000 / max(400, 780 + tail) * 60 + 40
                    route.extra["winds"] = {"tailwind_kmh": round(tail), "adjusted_minutes": round(adjusted), "samples": len(components)}
            if route.summary in ("", "Main route"):
                try:
                    middle = await weather.reverse_geocode(*route.coords[len(route.coords) // 2])
                    route.summary = f"via {middle.get('name')}"
                except Exception:
                    route.summary = "Main route"
            results.append({
                "summary": route.summary,
                "source": route.source,
                "distance_km": round(route.meters / 1000, 1),
                "duration_min": round(route.seconds / 60),
                "depart": depart.isoformat(),
                "arrive": (depart + timedelta(seconds=route.seconds)).isoformat(),
                "geometry": _simplify(route.coords),
                "points": chosen["points"],
                "hazards": spans(chosen["points"], mode, names),
                "risk": {"score": chosen["score"], "label": risk_label(chosen["score"])},
                "night_share": round(chosen["night"], 2),
                "departures": departures,
                "best_departure": recommend,
                "alerts": active,
                "extra": route.extra,
            })
        results.sort(key=lambda r: (round(r["risk"]["score"], 1), r["duration_min"]))
        return {"mode": mode, "mode_label": MODES[mode]["label"], "origin": origin, "destination": destination, "generated_at": now.isoformat(), "routes": results}

    return await _plan_cache.get_or_set(key, load)


def brief(trip: dict[str, Any], index: int = 0) -> dict[str, Any]:
    route = trip["routes"][index]
    return {
        "from": trip["origin"].get("name"), "to": trip["destination"].get("name"), "mode": trip["mode_label"],
        "distance_km": route["distance_km"], "duration_min": route["duration_min"], "depart": route["depart"], "arrive": route["arrive"],
        "risk": route["risk"]["label"], "night_share": route["night_share"],
        "hazards": [{k: h[k] for k in ("kind", "severity", "detail", "from_km", "to_km", "from_eta", "to_eta", "near")} for h in route["hazards"][:6]],
        "best_departure": route["best_departure"], "official_alerts": [{"event": a.get("event"), "severity": a.get("severity"), "near": a.get("near"), "headline": a.get("headline")} for a in route["alerts"][:5]],
        "extra": {k: v for k, v in route["extra"].items() if k in ("from_airport", "to_airport", "from_station", "to_station", "winds")},
        "route": route["summary"],
        "alternatives": [{"summary": r["summary"], "distance_km": r["distance_km"], "duration_min": r["duration_min"], "risk": r["risk"]["label"]} for i, r in enumerate(trip["routes"]) if i != index],
    }
