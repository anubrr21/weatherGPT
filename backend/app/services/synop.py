import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

STATIONS = Path(__file__).resolve().parent.parent / "data" / "india_wmo_stations.json"

PERIOD_HOURS = {"1": 6, "2": 12, "3": 18, "4": 24, "5": 1, "6": 2, "7": 3, "8": 9, "9": 15}


@lru_cache
def stations() -> dict[str, dict[str, Any]]:
    return json.loads(STATIONS.read_text(encoding="utf-8")) if STATIONS.exists() else {}


def present_weather(ww: int) -> str | None:
    if ww <= 3:
        return None
    table = [
        (4, 4, "smoke"), (5, 5, "haze"), (6, 9, "dust"), (10, 10, "mist"), (11, 12, "shallow fog"),
        (13, 13, "lightning"), (14, 16, "rain in sight"), (17, 17, "thunderstorm"), (18, 18, "squalls"),
        (19, 19, "funnel cloud"), (20, 20, "recent drizzle"), (21, 21, "recent rain"), (22, 24, "recent snow or freezing rain"),
        (25, 25, "recent rain showers"), (26, 27, "recent snow or hail showers"), (28, 28, "recent fog"),
        (29, 29, "recent thunderstorm"), (30, 35, "duststorm"), (36, 39, "blowing snow"), (40, 49, "fog"),
        (50, 59, "drizzle"), (60, 61, "light rain"), (62, 63, "moderate rain"), (64, 65, "heavy rain"),
        (66, 69, "freezing rain or sleet"), (70, 79, "snow"), (80, 80, "light rain showers"),
        (81, 81, "moderate rain showers"), (82, 82, "violent rain showers"), (83, 90, "snow, sleet or hail showers"),
        (91, 94, "rain after recent thunderstorm"), (95, 95, "thunderstorm with rain"), (96, 96, "thunderstorm with hail"),
        (97, 97, "heavy thunderstorm with rain"), (98, 98, "thunderstorm with duststorm"), (99, 99, "heavy thunderstorm with hail"),
    ]
    return next((label for lo, hi, label in table if lo <= ww <= hi), None)


def visibility_km(vv: str) -> float | None:
    if not vv.isdigit():
        return None
    v = int(vv)
    if v <= 50:
        return v / 10
    if 56 <= v <= 80:
        return float(v - 50)
    if 81 <= v <= 88:
        return float(30 + (v - 80) * 5)
    if v == 89:
        return 70.0
    return {90: 0.05, 91: 0.05, 92: 0.2, 93: 0.5, 94: 1, 95: 2, 96: 4, 97: 10, 98: 20, 99: 50}.get(v)


def _signed_tenths(group: str) -> float | None:
    sign, digits = group[1], group[2:5]
    if not digits.isdigit() or sign not in "01":
        return None
    value = int(digits) / 10
    return -value if sign == "1" else value


def _pressure(digits: str) -> float | None:
    if not digits.isdigit():
        return None
    value = int(digits) / 10
    return value + 1000 if value < 500 else value


def decode_report(tokens: list[str], day: int, hour: int, wind_unit: str, base: datetime) -> dict[str, Any] | None:
    if len(tokens) < 3 or not re.fullmatch(r"\d{5}", tokens[0]) or tokens[1] == "NIL":
        return None
    station = tokens[0]
    ir_ix_h_vv, n_dd_ff = tokens[1], tokens[2]
    i = 3
    obs: dict[str, Any] = {"station": station}
    meta = stations().get(station)
    if meta:
        obs.update(name=meta["name"], lat=meta["lat"], lon=meta["lon"], icao=meta.get("icao"))
    obs["visibility_km"] = visibility_km(ir_ix_h_vv[3:5]) if len(ir_ix_h_vv) == 5 else None
    if len(n_dd_ff) == 5 and n_dd_ff[1:3].isdigit() and n_dd_ff[3:5].isdigit():
        obs["cloud_oktas"] = int(n_dd_ff[0]) if n_dd_ff[0].isdigit() and n_dd_ff[0] != "9" else None
        direction, speed = int(n_dd_ff[1:3]), int(n_dd_ff[3:5])
        if speed == 99 and len(tokens) > 3 and tokens[3].startswith("00"):
            speed = int(tokens[3][2:]) if tokens[3][2:].isdigit() else speed
            i = 4
        factor = 1.852 if wind_unit in "34" else 3.6
        obs["wind_dir_deg"] = None if direction in (0, 99) else direction * 10
        obs["wind_kmh"] = round(speed * factor, 1)
    while i < len(tokens):
        group = tokens[i]
        i += 1
        if group in ("333", "555", "444", "222"):
            break
        if len(group) != 5:
            continue
        kind = group[0]
        if kind == "1":
            obs["temp_c"] = _signed_tenths(group)
        elif kind == "2":
            if group[1] == "9" and group[2:5].isdigit():
                obs["humidity_pct"] = int(group[2:5])
            else:
                obs["dewpoint_c"] = _signed_tenths(group)
        elif kind == "3":
            obs["station_pressure_hpa"] = _pressure(group[1:5])
        elif kind == "4" and group[1] in "09":
            obs["pressure_hpa"] = _pressure(group[1:5])
        elif kind == "6" and group[1:4].isdigit():
            rrr = int(group[1:4])
            obs["rain_mm"] = round((rrr - 990) / 10, 1) if rrr >= 990 else float(rrr)
            obs["rain_period_h"] = PERIOD_HOURS.get(group[4])
        elif kind == "7" and group[1:3].isdigit():
            obs["weather"] = present_weather(int(group[1:3]))
    if "temp_c" in obs and "dewpoint_c" in obs and "humidity_pct" not in obs and obs["temp_c"] is not None and obs["dewpoint_c"] is not None:
        import math

        t, td = obs["temp_c"], obs["dewpoint_c"]
        obs["humidity_pct"] = round(100 * math.exp(17.625 * td / (243.04 + td)) / math.exp(17.625 * t / (243.04 + t)))
    observed = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        observed = observed.replace(day=day, hour=hour)
    except ValueError:
        return None
    if observed - base > timedelta(days=2):
        observed = (observed.replace(day=1) - timedelta(days=1)).replace(day=day, hour=hour)
    obs["observed_at"] = observed
    obs["raw"] = " ".join(tokens)
    return obs


def decode_bulletin(text: str, received: datetime | None = None) -> list[dict[str, Any]]:
    base = received or datetime.now(timezone.utc)
    body = text.replace("\r", "\n")
    match = re.search(r"\bAAXX\s+(\d{2})(\d{2})(\d)", body)
    if not match:
        return []
    day, hour, wind_unit = int(match.group(1)), int(match.group(2)), match.group(3)
    reports = body[match.end():].split("=")
    out = []
    for chunk in reports:
        tokens = chunk.split()
        if not tokens:
            continue
        decoded = decode_report(tokens, day, hour, wind_unit, base)
        if decoded:
            out.append(decoded)
    return out
