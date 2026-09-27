import json
import sys
import time
from pathlib import Path

import httpx
import numpy as np

OUT = Path(__file__).resolve().parent.parent / "data" / "rail"
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
UA = {"User-Agent": "WeatherGPT/0.1 (rail graph builder)"}
LAT_RANGE = (6.0, 37.5)
LON_RANGE = (68.0, 97.5)
STEP = 2.0
WAYS = '[out:json][timeout:170];way["railway"="rail"]["usage"~"^(main|branch)$"][!"service"]({s},{w},{n},{e});out skel geom;'
STATIONS = '[out:json][timeout:170];node["railway"="station"]["name"]({s},{w},{n},{e});out;'
INDIA = [(8.0, 77.0), (13.0, 80.3), (19.0, 72.8), (22.5, 88.3), (28.6, 77.2), (26.1, 91.7), (23.0, 72.6), (17.4, 78.5), (21.2, 81.6), (30.7, 76.8), (34.1, 74.8), (11.0, 76.9), (25.6, 85.1), (20.3, 85.8), (26.9, 75.8)]


def fetch(query: str, attempt: int = 0) -> list[dict]:
    url = OVERPASS[(attempt + fetch.turn) % len(OVERPASS)]
    fetch.turn += 1
    try:
        response = httpx.post(url, data={"data": query}, headers=UA, timeout=200)
        if response.status_code == 200:
            return response.json().get("elements", [])
        print(f"  {url} -> {response.status_code}", flush=True)
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  {url} -> {type(exc).__name__}", flush=True)
    if attempt >= 5:
        raise RuntimeError("overpass kept failing")
    time.sleep(15 * (attempt + 1))
    return fetch(query, attempt + 1)


fetch.turn = 0


def tiles():
    lat = LAT_RANGE[0]
    while lat < LAT_RANGE[1]:
        lon = LON_RANGE[0]
        while lon < LON_RANGE[1]:
            s, w, n, e = lat, lon, min(lat + STEP, LAT_RANGE[1]), min(lon + STEP, LON_RANGE[1])
            if any(s - 6 <= a <= n + 6 and w - 6 <= b <= e + 6 for a, b in INDIA):
                yield s, w, n, e
            lon += STEP
        lat += STEP


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = OUT / "tiles"
    cache.mkdir(exist_ok=True)
    boxes = list(tiles())
    print(f"{len(boxes)} tiles", flush=True)
    ways: dict[int, list[tuple[int, float, float]]] = {}
    stations: dict[int, tuple[str, float, float]] = {}
    for i, (s, w, n, e) in enumerate(boxes, 1):
        path = cache / f"{s}_{w}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"ways": fetch(WAYS.format(s=s, w=w, n=n, e=e)), "stations": fetch(STATIONS.format(s=s, w=w, n=n, e=e))}
            path.write_text(json.dumps(data), encoding="utf-8")
            time.sleep(2)
        for way in data["ways"]:
            ways[way["id"]] = [(node, p["lat"], p["lon"]) for node, p in zip(way.get("nodes", []), way.get("geometry", [])) if p]
        for node in data["stations"]:
            name = node.get("tags", {}).get("name:en") or node.get("tags", {}).get("name")
            if name:
                stations[node["id"]] = (name, node["lat"], node["lon"])
        print(f"[{i}/{len(boxes)}] {s},{w}: {len(data['ways'])} ways, {len(data['stations'])} stations (total {len(ways)} ways)", flush=True)

    index: dict[int, int] = {}
    coords: list[tuple[float, float]] = []
    edges: list[tuple[int, int, float]] = []

    def node_id(osm: int, lat: float, lon: float) -> int:
        if osm not in index:
            index[osm] = len(coords)
            coords.append((lat, lon))
        return index[osm]

    for points in ways.values():
        for (a, alat, alon), (b, blat, blon) in zip(points, points[1:]):
            ia, ib = node_id(a, alat, alon), node_id(b, blat, blon)
            p1, p2 = np.radians([alat, blat])
            dlat, dlon = p2 - p1, np.radians(blon - alon)
            h = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
            edges.append((ia, ib, float(6371000 * 2 * np.arcsin(np.sqrt(h)))))

    xy = np.asarray(coords, dtype=np.float32)
    e = np.asarray(edges, dtype=np.float64)
    names = [v[0] for v in stations.values()]
    st = np.asarray([[v[1], v[2]] for v in stations.values()], dtype=np.float32)
    np.savez_compressed(OUT / "india_rail.npz", coords=xy, src=e[:, 0].astype(np.int32), dst=e[:, 1].astype(np.int32), meters=e[:, 2].astype(np.float32), station_xy=st)
    (OUT / "stations.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    km = e[:, 2].sum() / 1000 if len(e) else 0
    print(f"graph: {len(coords)} nodes, {len(edges)} edges, {km:,.0f} km of track, {len(names)} stations", flush=True)


if __name__ == "__main__":
    sys.exit(main())
