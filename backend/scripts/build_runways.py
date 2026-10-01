import csv
import io
import json
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
RUNWAYS = "https://davidmegginson.github.io/ourairports-data/runways.csv"
AIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"


def rows(url: str) -> list[dict[str, str]]:
    with urllib.request.urlopen(url) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode("utf-8"))))


def number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    wanted = {a["icao"] for a in json.loads((DATA / "india_airports.json").read_text(encoding="utf-8"))}
    elevation = {r["ident"]: number(r["elevation_ft"]) for r in rows(AIRPORTS) if r["ident"] in wanted}
    out: dict[str, dict] = {icao: {"elevation_ft": elevation.get(icao), "runways": []} for icao in sorted(wanted)}
    for r in rows(RUNWAYS):
        icao = r["airport_ident"]
        if icao not in wanted or r["closed"] == "1":
            continue
        ends = []
        for side in ("le", "he"):
            heading = number(r[f"{side}_heading_degT"])
            ident = r[f"{side}_ident"]
            if heading is None and ident[:2].isdigit():
                heading = int(ident[:2]) * 10
            if ident and heading is not None:
                ends.append({"id": ident, "heading": round(heading)})
        if ends:
            out[icao]["runways"].append({"length_ft": number(r["length_ft"]), "surface": r["surface"] or None, "ends": ends})
    (DATA / "india_runways.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(len(out), "airports,", sum(len(v["runways"]) for v in out.values()), "runways,", sum(1 for v in out.values() if not v["runways"]), "without runway data")


if __name__ == "__main__":
    main()
