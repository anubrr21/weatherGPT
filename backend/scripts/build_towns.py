import json
import sys
import time
from pathlib import Path

import osmium

ROOT = Path(__file__).resolve().parent.parent
PBF = ROOT / "data" / "rail" / "india-latest.osm.pbf"
TARGET = ROOT / "app" / "data" / "india_towns.json"
KINDS = ("city", "town")


def main() -> None:
    if not PBF.exists():
        sys.exit(f"missing {PBF}; download https://download.geofabrik.de/asia/india-latest.osm.pbf there first")
    started = time.perf_counter()
    towns = []
    processor = osmium.FileProcessor(str(PBF), osmium.osm.NODE).with_filter(osmium.filter.TagFilter(*(("place", k) for k in KINDS)))
    for node in processor:
        tags = node.tags
        name = tags.get("name:en") or tags.get("name")
        if not name or not node.location.valid():
            continue
        population = None
        raw = (tags.get("population") or "").replace(",", "").strip()
        if raw.isdigit():
            population = int(raw)
        towns.append({"name": name, "kind": tags.get("place"), "lat": round(node.location.lat, 4), "lon": round(node.location.lon, 4), "population": population})
    towns.sort(key=lambda t: -(t["population"] or 0))
    TARGET.write_text(json.dumps({"source": "OpenStreetMap contributors, Geofabrik India extract", "built": time.strftime("%Y-%m-%d"), "towns": towns}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with_pop = sum(1 for t in towns if t["population"])
    print(f"{len(towns):,} cities and towns ({with_pop:,} with population) in {time.perf_counter() - started:.0f}s -> {TARGET}")


if __name__ == "__main__":
    main()
