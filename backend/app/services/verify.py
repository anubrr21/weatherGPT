import asyncio
import csv
import io
import math
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from app.services.cyclones import km
from app.services.http import TTLCache, get_retry
from app.services.trips import airports

IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
UA = {"User-Agent": "WeatherGPT/0.1"}
MODELS = [
    ("best_match", "WeatherGPT blend"),
    ("ecmwf_ifs025", "ECMWF IFS"),
    ("gfs_seamless", "NOAA GFS"),
    ("icon_seamless", "DWD ICON"),
    ("ukmo_seamless", "UK Met Office"),
    ("jma_seamless", "JMA"),
    ("meteofrance_seamless", "Météo-France"),
    ("gem_seamless", "Canada GEM"),
    ("cma_grapes_global", "CMA GRAPES"),
]
VARIABLES = {"temp": "temperature_2m", "dew": "dew_point_2m", "wind": "wind_speed_10m", "rain": "precipitation"}
LEADS = (1, 2)
RAIN_CODES = ("RA", "DZ", "SH", "TS", "GR", "GS")
RAIN_MM = 0.2
_obs_cache = TTLCache(ttl_s=3 * 3600)
_run_cache = TTLCache(ttl_s=3 * 3600)
_card_cache = TTLCache(ttl_s=3 * 3600)


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def hourly_observations(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    best: dict[str, tuple[float, dict[str, Any]]] = {}
    rain_hours: dict[str, bool] = {}
    for row in rows:
        try:
            when = datetime.strptime(row["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        codes = (row.get("wxcodes") or "").upper()
        hour = (when + timedelta(minutes=30)).replace(minute=0)
        own = when.replace(minute=0).isoformat()
        rain_hours[own] = rain_hours.get(own, False) or (codes not in ("", "M") and any(c in codes for c in RAIN_CODES))
        offset = abs((when - hour).total_seconds()) / 60
        if offset > 20:
            continue
        temp, dew, knots = _num(row.get("tmpf", "")), _num(row.get("dwpf", "")), _num(row.get("sknt", ""))
        entry = {
            "temp": round((temp - 32) * 5 / 9, 1) if temp is not None else None,
            "dew": round((dew - 32) * 5 / 9, 1) if dew is not None else None,
            "wind": round(knots * 1.852, 1) if knots is not None else None,
        }
        key = hour.isoformat()
        if key not in best or offset < best[key][0]:
            best[key] = (offset, entry)
    out = {key: entry | {"rain": rain_hours.get(key)} for key, (_, entry) in best.items()}
    for key, raining in rain_hours.items():
        out.setdefault(key, {"temp": None, "dew": None, "wind": None, "rain": raining})
    return dict(sorted(out.items()))


async def observations(icao: str, days: int) -> dict[str, dict[str, Any]]:
    async def load() -> dict[str, dict[str, Any]]:
        end = datetime.now(timezone.utc) + timedelta(days=1)
        start = end - timedelta(days=days + 1)
        response = await get_retry(IEM, params=[
            ("station", icao), ("data", "tmpf"), ("data", "dwpf"), ("data", "sknt"), ("data", "wxcodes"),
            ("year1", start.year), ("month1", start.month), ("day1", start.day), ("year2", end.year), ("month2", end.month), ("day2", end.day),
            ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("report_type", 3), ("report_type", 4),
        ], headers=UA, timeout=60)
        return hourly_observations(list(csv.DictReader(io.StringIO(response.text))))

    return await _obs_cache.get_or_set(f"{icao}:{days}", load)


async def model_runs(lat: float, lon: float, days: int) -> dict[str, dict[str, dict[int, dict[str, float]]]]:
    async def load() -> dict[str, dict[str, dict[int, dict[str, float]]]]:
        hourly = ",".join(f"{v}_previous_day{lead}" for v in VARIABLES.values() for lead in LEADS)
        response = await get_retry(PREVIOUS, params={
            "latitude": lat, "longitude": lon, "hourly": hourly, "models": ",".join(m for m, _ in MODELS),
            "past_days": days, "forecast_days": 1, "timezone": "UTC", "wind_speed_unit": "kmh",
        }, timeout=60)
        data = response.json()
        times = [t + ":00+00:00" if len(t) == 16 else t for t in data["hourly"]["time"]]
        out: dict[str, dict[str, dict[int, dict[str, float]]]] = {}
        for model, _ in MODELS:
            for short, name in VARIABLES.items():
                for lead in LEADS:
                    series = data["hourly"].get(f"{name}_previous_day{lead}_{model}") or []
                    out.setdefault(model, {}).setdefault(short, {})[lead] = {t: v for t, v in zip(times, series) if v is not None}
        return out

    return await _run_cache.get_or_set(f"{lat:.3f},{lon:.3f}:{days}", load)


def continuous(pairs: list[tuple[float, float]]) -> dict[str, Any] | None:
    if len(pairs) < 12:
        return None
    errors = [f - o for f, o in pairs]
    return {
        "mae": round(sum(abs(e) for e in errors) / len(errors), 2), "bias": round(sum(errors) / len(errors), 2),
        "rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2), "n": len(errors),
    }


def categorical(pairs: list[tuple[bool, bool]]) -> dict[str, Any] | None:
    if len(pairs) < 24:
        return None
    hits = sum(1 for f, o in pairs if f and o)
    misses = sum(1 for f, o in pairs if not f and o)
    false_alarms = sum(1 for f, o in pairs if f and not o)
    correct_neg = sum(1 for f, o in pairs if not f and not o)
    n = len(pairs)
    expected = ((hits + misses) * (hits + false_alarms) + (correct_neg + misses) * (correct_neg + false_alarms)) / n
    return {
        "pod": round(hits / (hits + misses), 2) if hits + misses else None,
        "far": round(false_alarms / (hits + false_alarms), 2) if hits + false_alarms else None,
        "csi": round(hits / (hits + misses + false_alarms), 2) if hits + misses + false_alarms else None,
        "hss": round((hits + correct_neg - expected) / (n - expected), 2) if n != expected else None,
        "observed_rain_hours": hits + misses, "n": n,
    }


def score(obs: dict[str, dict[str, Any]], runs: dict[str, dict[str, dict[int, dict[str, float]]]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {}
    for model, _ in MODELS:
        model_scores: dict[str, Any] = {}
        for short in VARIABLES:
            for lead in LEADS:
                series = runs.get(model, {}).get(short, {}).get(lead, {})
                if short == "rain":
                    pairs_c = [(series[t] >= RAIN_MM, bool(o["rain"])) for t, o in obs.items() if o.get("rain") is not None and t in series and datetime.fromisoformat(t) < now]
                    model_scores.setdefault(short, {})[lead] = categorical(pairs_c)
                else:
                    pairs = [(series[t], o[short]) for t, o in obs.items() if o.get(short) is not None and t in series and datetime.fromisoformat(t) < now]
                    model_scores.setdefault(short, {})[lead] = continuous(pairs)
        out[model] = model_scores
    return out


def nearest_stations(lat: float, lon: float, limit: int = 3, max_km: float = 250) -> list[dict[str, Any]]:
    ranked = sorted(
        (a | {"km": round(km((lat, lon), (a["lat"], a["lon"])), 1)} for a in airports() if a.get("icao", "").startswith("V")),
        key=lambda a: a["km"],
    )
    return [a for a in ranked if a["km"] <= max_km][:limit]


def leaderboard(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    board = []
    for model, label in MODELS:
        totals: dict[str, list[tuple[float, int]]] = {"temp": [], "dew": [], "wind": []}
        rain: list[tuple[float, int]] = []
        for station in stations:
            scores = station["scores"].get(model, {})
            for short in totals:
                s = (scores.get(short) or {}).get(1)
                if s:
                    totals[short].append((s["mae"], s["n"]))
            r = (scores.get("rain") or {}).get(1)
            if r and r.get("hss") is not None:
                rain.append((r["hss"], r["n"]))
        entry: dict[str, Any] = {"model": model, "label": label}
        for short, values in totals.items():
            n = sum(c for _, c in values)
            entry[f"{short}_mae"] = round(sum(v * c for v, c in values) / n, 2) if n else None
        n = sum(c for _, c in rain)
        entry["rain_hss"] = round(sum(v * c for v, c in rain) / n, 2) if n else None
        board.append(entry)
    for short in ("temp", "dew", "wind"):
        values = [e[f"{short}_mae"] for e in board if e[f"{short}_mae"] is not None]
        middle = median(values) if values else None
        for e in board:
            e[f"{short}_rel"] = round(e[f"{short}_mae"] / middle, 3) if middle and e[f"{short}_mae"] is not None else None
    for e in board:
        parts = [e[k] for k in ("temp_rel", "dew_rel", "wind_rel") if e[k] is not None]
        e["index"] = round(sum(parts) / len(parts), 3) if parts else None
    board.sort(key=lambda e: (e["index"] is None, e["index"] or 0))
    for rank, e in enumerate(board, 1):
        e["rank"] = rank
    return board


async def scorecard(lat: float, lon: float, days: int = 10) -> dict[str, Any]:
    key = f"{round(lat, 1)},{round(lon, 1)}:{days}"

    async def load() -> dict[str, Any]:
        candidates = nearest_stations(lat, lon, limit=5)
        loaded = await asyncio.gather(*(asyncio.gather(observations(s["icao"], days), model_runs(s["lat"], s["lon"], days)) for s in candidates), return_exceptions=True)
        stations = []
        for station, result in zip(candidates, loaded):
            if isinstance(result, Exception):
                continue
            obs, runs = result
            if sum(1 for o in obs.values() if o.get("temp") is not None) < 24:
                continue
            scores = score(obs, runs)
            recent = [t for t in obs if datetime.fromisoformat(t) >= datetime.now(timezone.utc) - timedelta(days=7)]
            series = {
                "time": recent,
                "observed": [obs[t]["temp"] for t in recent],
                "rain": [obs[t]["rain"] for t in recent],
                "models": {m: [runs.get(m, {}).get("temp", {}).get(1, {}).get(t) for t in recent] for m in ("best_match", "ecmwf_ifs025", "gfs_seamless", "icon_seamless")},
            }
            stations.append({
                "icao": station["icao"], "iata": station.get("iata"), "name": station["name"], "city": station.get("city"), "lat": station["lat"], "lon": station["lon"], "km": station["km"],
                "observations": sum(1 for o in obs.values() if o.get("temp") is not None), "scores": scores, "series": series,
            })
            if len(stations) == 3:
                break
        board = leaderboard(stations)
        return {
            "generated": datetime.now(timezone.utc).isoformat(), "days": days, "stations": stations, "leaderboard": board,
            "best": board[0] if board and board[0]["index"] is not None else None,
            "models": [{"model": m, "label": label} for m, label in MODELS],
            "method": (
                "Each model's forecast made 1 and 2 days ahead (Open-Meteo previous runs) is compared hour by hour with METAR observations from the nearest IMD airport met offices "
                "(Iowa Environmental Mesonet archive). MAE is the average size of the error, bias its average sign (+ means too warm/windy). Rain is scored as rain or no rain in the hour: "
                "POD = share of rainy hours that were forecast, FAR = share of forecast rain that did not happen, HSS = skill above chance (1 is perfect, 0 no better than chance)."
            ),
        }

    return await _card_cache.get_or_set(key, load)


async def summary_for_agent(lat: float, lon: float, name: str) -> dict[str, Any]:
    card = await scorecard(lat, lon)
    return {
        "place": name, "days_verified": card["days"], "stations": [{"name": s["name"], "icao": s["icao"], "km": s["km"], "hours_observed": s["observations"]} for s in card["stations"]],
        "ranking_day_ahead": [{k: e[k] for k in ("rank", "label", "temp_mae", "dew_mae", "wind_mae", "rain_hss")} for e in card["leaderboard"]],
        "best_model_here": card["best"]["label"] if card["best"] else None,
        "bias_of_weathergpt_blend": {s["icao"]: {v: ((s["scores"].get("best_match", {}).get(v) or {}).get(1) or {}).get("bias") for v in ("temp", "dew", "wind")} for s in card["stations"]},
        "method": card["method"],
    }
