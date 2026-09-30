import csv
import json
import sys
import urllib.request
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "cyclones"
SOURCE = ROOT / "ibtracs.NI.list.v04r01.csv"
TARGET = ROOT / "ni_storms.json"
URL = "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.NI.list.v04r01.csv"
FIRST_SEASON = 1980
ONE_TO_THREE_MINUTE = 0.93


def number(value: str) -> float | None:
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        return None


def storm_name(raw: str) -> str | None:
    if raw in ("UNNAMED", "NOT_NAMED", ""):
        return None
    names: list[str] = []
    for part in raw.split(":"):
        name = part.split("-")[0].strip().title()
        if name and all(SequenceMatcher(None, name, known).ratio() < 0.75 for known in names):
            names.append(name)
    return " / ".join(names) or None


def wind(row: dict[str, str]) -> tuple[float | None, str | None]:
    for column, factor, source in (("NEWDELHI_WIND", 1.0, "IMD"), ("WMO_WIND", 1.0, "WMO"), ("USA_WIND", ONE_TO_THREE_MINUTE, "JTWC")):
        value = number(row[column])
        if value is not None and value > 0:
            return round(value * factor), source
    return None, None


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists() or "--refresh" in sys.argv:
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, SOURCE)
    storms: dict[str, dict] = {}
    with SOURCE.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        next(reader)
        for row in reader:
            season = int(row["SEASON"])
            if season < FIRST_SEASON or row["TRACK_TYPE"] not in ("main", "PROVISIONAL", "US-PROVISIONAL"):
                continue
            lat, lon = number(row["LAT"]), number(row["LON"])
            if lat is None or lon is None:
                continue
            when = datetime.strptime(row["ISO_TIME"], "%Y-%m-%d %H:%M:%S")
            if when.hour % 3:
                continue
            kt, source = wind(row)
            storm = storms.setdefault(row["SID"], {
                "sid": row["SID"], "name": storm_name(row["NAME"]),
                "season": season, "basin": None, "provisional": row["TRACK_TYPE"] != "main", "points": [], "sources": set(),
            })
            if source:
                storm["sources"].add(source)
            storm["points"].append([
                when.strftime("%Y-%m-%dT%H:%MZ"), round(lat, 2), round(lon, 2), kt,
                row["NEWDELHI_GRADE"].strip() or None, number(row["NEWDELHI_PRES"]) or number(row["WMO_PRES"]), number(row["DIST2LAND"]),
            ])
            if row["SUBBASIN"] in ("BB", "AS") and storm["basin"] is None:
                storm["basin"] = row["SUBBASIN"]
    out = []
    for storm in storms.values():
        winds = [p[3] for p in storm["points"] if p[3] is not None]
        if not winds or max(winds) < 17:
            continue
        storm["peak_kt"] = max(winds)
        storm["landfalls"] = [p[:3] for prev, p in zip(storm["points"], storm["points"][1:]) if prev[6] and prev[6] > 0 and p[6] == 0]
        storm["sources"] = sorted(storm["sources"])
        out.append(storm)
    out.sort(key=lambda s: s["points"][0][0])
    TARGET.write_text(json.dumps({"built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": URL, "storms": out}, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} storms {out[0]['season']}-{out[-1]['season']}, {sum(len(s['points']) for s in out)} fixes, {TARGET.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
