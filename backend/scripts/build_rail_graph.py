import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import osmium

DATA = Path(__file__).resolve().parent.parent / "data" / "rail"
PBF = DATA / "india-latest.osm.pbf"
SKIP_SERVICE = {"yard", "siding", "spur", "crossover"}
SKIP_USAGE = {"industrial", "military", "test", "tourism", "freight"}
SNAP_M = 1000
CELL = 0.02


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, h)))


def rail_ways(pbf: Path) -> list[list[int]]:
    ways = []
    for way in osmium.FileProcessor(str(pbf), osmium.osm.WAY).with_filter(osmium.filter.TagFilter(("railway", "rail"))):
        tags = way.tags
        if tags.get("service") in SKIP_SERVICE or tags.get("usage") in SKIP_USAGE:
            continue
        refs = [n.ref for n in way.nodes]
        if len(refs) >= 2:
            ways.append(refs)
    return ways


def stations(pbf: Path) -> list[tuple[str, float, float]]:
    found = []
    processor = osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.TagFilter(("railway", "station"), ("railway", "halt")))
    for node in processor:
        tags = node.tags
        name = tags.get("name:en") or tags.get("name")
        if name and node.location.valid() and tags.get("station") not in ("subway", "light_rail", "monorail"):
            found.append((name, node.location.lat, node.location.lon))
    return found


def locations(pbf: Path, ids: set[int]) -> dict[int, tuple[float, float]]:
    out = {}
    for node in osmium.FileProcessor(str(pbf), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(ids)):
        if node.location.valid():
            out[node.id] = (node.location.lat, node.location.lon)
    return out


def main() -> None:
    if not PBF.exists():
        sys.exit(f"missing {PBF}; download https://download.geofabrik.de/asia/india-latest.osm.pbf there first")
    started = time.perf_counter()
    ways = rail_ways(PBF)
    print(f"{len(ways):,} railway ways ({time.perf_counter() - started:.0f}s)", flush=True)
    halts = stations(PBF)
    print(f"{len(halts):,} named stations and halts ({time.perf_counter() - started:.0f}s)", flush=True)
    needed = {ref for refs in ways for ref in refs}
    where = locations(PBF, needed)
    print(f"{len(where):,} track points located ({time.perf_counter() - started:.0f}s)", flush=True)

    ways = [[r for r in refs if r in where] for refs in ways]
    ways = [refs for refs in ways if len(refs) >= 2]
    degree: dict[int, int] = defaultdict(int)
    for refs in ways:
        for a, b in zip(refs, refs[1:]):
            degree[a] += 1
            degree[b] += 1

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ref in degree:
        lat, lon = where[ref]
        grid[(int(lat / CELL), int(lon / CELL))].append(ref)

    snapped: list[tuple[str, float, float, int]] = []
    for name, lat, lon in halts:
        cx, cy = int(lat / CELL), int(lon / CELL)
        best, best_d = None, float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for ref in grid.get((cx + dx, cy + dy), ()):
                    d = haversine((lat, lon), where[ref])
                    if d < best_d:
                        best, best_d = ref, d
        if best is not None and best_d <= SNAP_M:
            snapped.append((name, lat, lon, best))

    keep = {ref for ref, d in degree.items() if d != 2} | {refs[0] for refs in ways} | {refs[-1] for refs in ways} | {s[3] for s in snapped}
    index: dict[int, int] = {}
    node_xy: list[tuple[float, float]] = []

    def node(ref: int) -> int:
        if ref not in index:
            index[ref] = len(node_xy)
            node_xy.append(where[ref])
        return index[ref]

    edge_a, edge_b, edge_m, geo_start, geo_end = [], [], [], [], []
    geo_xy: list[tuple[float, float]] = []
    for refs in ways:
        segment = [refs[0]]
        for ref in refs[1:]:
            segment.append(ref)
            if ref in keep:
                points = [where[r] for r in segment]
                meters = sum(haversine(p, q) for p, q in zip(points, points[1:]))
                if meters > 0:
                    edge_a.append(node(segment[0]))
                    edge_b.append(node(segment[-1]))
                    edge_m.append(meters)
                    geo_start.append(len(geo_xy))
                    geo_xy.extend(points)
                    geo_end.append(len(geo_xy))
                segment = [ref]

    station_names = [s[0] for s in snapped]
    np.savez_compressed(
        DATA / "india_rail.npz",
        node_xy=np.asarray(node_xy, dtype=np.float32),
        edge_a=np.asarray(edge_a, dtype=np.int32),
        edge_b=np.asarray(edge_b, dtype=np.int32),
        edge_m=np.asarray(edge_m, dtype=np.float32),
        geo_start=np.asarray(geo_start, dtype=np.int32),
        geo_end=np.asarray(geo_end, dtype=np.int32),
        geo_xy=np.asarray(geo_xy, dtype=np.float32),
        station_xy=np.asarray([[s[1], s[2]] for s in snapped], dtype=np.float32),
        station_node=np.asarray([node(s[3]) for s in snapped], dtype=np.int32),
    )
    (DATA / "stations.json").write_text(json.dumps(station_names, ensure_ascii=False), encoding="utf-8")
    print(
        f"graph: {len(node_xy):,} junction and station nodes, {len(edge_a):,} edges, {sum(edge_m) / 1000:,.0f} km of track, "
        f"{len(snapped):,} stations on the network ({time.perf_counter() - started:.0f}s)",
        flush=True,
    )


if __name__ == "__main__":
    main()
