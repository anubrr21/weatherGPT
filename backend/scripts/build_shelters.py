import json
import re
import sys
import time
from pathlib import Path

import osmium

DATA = Path(__file__).resolve().parent.parent / "data"
PBF = DATA / "rail" / "india-latest.osm.pbf"
TARGET = DATA / "cyclones" / "shelters.json"
STORMS = DATA / "cyclones" / "ni_storms.json"
COASTAL_KM = 120
PUBLIC = {"school": "School", "college": "College", "community_centre": "Community hall", "townhall": "Town hall"}
NAME = re.compile(r"cyclone|\bmpcs\b|multi[ -]?purpose (cyclone |flood )?shelter|flood shelter|relief (centre|center|camp|shelter)|evacuation|తుఫాను|ଘୂର୍ଣ୍ଣିବାତ୍ୟା|ঘূর্ণিঝড়|चक्रवात|புயல்", re.I)
KEYS = ("name", "emergency", "amenity")
NOT_SHELTER = re.compile(r"\b(gym|fitness|cafe|restaurant|hotel|shop|store|wear|warning cent(re|er)|meteorolog\w*|radar|office)\b", re.I)


def kind(tags: dict[str, str]) -> str | None:
    name = " ".join(tags.get(k, "") for k in ("name", "name:en", "official_name", "description"))
    if name.strip() and NOT_SHELTER.search(name):
        return None
    if re.search(r"cyclone|\bmpcs\b|తుఫాను|ଘୂର୍ଣ୍ଣିବାତ୍ୟା|ঘূর্ণিঝড়|चक्रवात|புயல்", name, re.I):
        return "cyclone"
    if NAME.search(name):
        return "relief"
    if tags.get("emergency") == "shelter" or tags.get("amenity") == "shelter" and tags.get("shelter_type") in ("emergency", "evacuation"):
        return "relief"
    if tags.get("emergency") == "assembly_point":
        return "assembly"
    if tags.get("amenity") in PUBLIC and (tags.get("name") or tags.get("name:en")):
        return "public"
    return None


def coastal_cells() -> set[tuple[int, int]]:
    storms = json.loads(STORMS.read_text(encoding="utf-8"))["storms"]
    cells = set()
    reach = COASTAL_KM / 111
    for storm in storms:
        for _, lat, lon in storm["landfalls"]:
            for dlat in range(-3, 4):
                for dlon in range(-3, 4):
                    if (dlat * 0.5) ** 2 + (dlon * 0.5) ** 2 <= (reach + 0.5) ** 2:
                        cells.add((int((lat + dlat * 0.5) // 0.5), int((lon + dlon * 0.5) // 0.5)))
    return cells


def record(obj, found: dict[str, dict]) -> list[int] | None:
    tags = {t.k: t.v for t in obj.tags}
    what = kind(tags)
    if not what:
        return None
    ref = f"{'node' if isinstance(obj, osmium.osm.Node) else 'way'}/{obj.id}"
    found[ref] = {"osm": ref, "kind": what, "name": tags.get("name:en") or tags.get("name"), "capacity": tags.get("capacity"), "district": tags.get("addr:district"), "operator": tags.get("operator"), "type": PUBLIC.get(tags.get("amenity", ""))}
    if isinstance(obj, osmium.osm.Node):
        if obj.location.valid():
            found[ref] |= {"lat": round(obj.location.lat, 6), "lon": round(obj.location.lon, 6)}
        return None
    return [n.ref for n in obj.nodes][:12]


def main() -> None:
    if not PBF.exists():
        sys.exit(f"missing {PBF}; download https://download.geofabrik.de/asia/india-latest.osm.pbf there first")
    started = time.perf_counter()
    found: dict[str, dict] = {}
    way_refs: dict[str, list[int]] = {}
    processor = osmium.FileProcessor(str(PBF), osmium.osm.NODE | osmium.osm.WAY).with_filter(osmium.filter.KeyFilter(*KEYS))
    for obj in processor:
        refs = record(obj, found)
        if refs:
            way_refs[f"way/{obj.id}"] = refs
    print(f"{len(found):,} candidates ({time.perf_counter() - started:.0f}s)", flush=True)
    needed = {r for refs in way_refs.values() for r in refs}
    where = {}
    for node in osmium.FileProcessor(str(PBF), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(needed)):
        if node.location.valid():
            where[node.id] = (node.location.lat, node.location.lon)
    for ref, refs in way_refs.items():
        points = [where[r] for r in refs if r in where]
        if points:
            found[ref] |= {"lat": round(sum(p[0] for p in points) / len(points), 6), "lon": round(sum(p[1] for p in points) / len(points), 6)}
    cells = coastal_cells()
    shelters = [
        {k: v for k, v in s.items() if v is not None}
        for s in found.values()
        if "lat" in s and (s["kind"] != "public" or (int(s["lat"] // 0.5), int(s["lon"] // 0.5)) in cells)
    ]
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps({"source": "OpenStreetMap contributors, Geofabrik India extract", "built": time.strftime("%Y-%m-%d"), "shelters": shelters}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts = {k: sum(1 for s in shelters if s["kind"] == k) for k in ("cyclone", "relief", "assembly", "public")}
    print(f"{len(shelters):,} shelters {counts} in {time.perf_counter() - started:.0f}s -> {TARGET}")


if __name__ == "__main__":
    main()
