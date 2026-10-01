import asyncio
import csv
import io
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.db import Observation, Session, utcnow
from app.services import weather
from app.services.cyclones import km

RADIUS_KM = 200
EXPORTS = ("forecast", "models", "climate", "observations")


async def stations(lat: float, lon: float, hours: int = 72) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(hours=hours)
    pad = RADIUS_KM / 100
    async with Session() as s:
        rows = (await s.scalars(
            select(Observation)
            .where(Observation.observed_at >= since, Observation.lat.between(lat - pad, lat + pad), Observation.lon.between(lon - pad * 1.2, lon + pad * 1.2))
            .order_by(Observation.observed_at)
        )).all()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        distance = km((lat, lon), (row.lat, row.lon))
        if distance > RADIUS_KM:
            continue
        entry = grouped.setdefault(row.station, {"station": row.station, "name": row.name, "lat": row.lat, "lon": row.lon, "km": round(distance), "kind": "IMD synoptic" if row.station.isdigit() else "Airport METAR", "series": []})
        observed = row.observed_at if row.observed_at.tzinfo else row.observed_at.replace(tzinfo=timezone.utc)
        entry["series"].append({
            "time": observed.isoformat(), "temp_c": row.temp_c, "dewpoint_c": row.dewpoint_c, "wind_kmh": row.wind_kmh, "gust_kmh": row.gust_kmh,
            "pressure_hpa": row.pressure_hpa, "weather": row.weather, "raw": row.raw,
        })
    out = sorted(grouped.values(), key=lambda g: g["km"])
    for g in out:
        g["count"] = len(g["series"])
        g["latest"] = g["series"][-1]
    return out[:12]


def model_stats(compare: dict[str, Any]) -> dict[str, Any]:
    days = compare.get("days") or []
    models = list((compare.get("models") or {}).keys())
    if not days or not models:
        return {}
    spread_t = [d.get("spread_tmax") or 0 for d in days]
    spread_r = [d.get("spread_rain") or 0 for d in days]
    totals = {m: round(sum((d.get(m) or {}).get("rain") or 0 for d in days), 1) for m in models}
    return {
        "mean_tmax_spread": round(sum(spread_t) / len(spread_t), 2), "max_tmax_spread": max(spread_t), "max_tmax_spread_date": days[spread_t.index(max(spread_t))]["date"],
        "max_rain_spread": max(spread_r), "max_rain_spread_date": days[spread_r.index(max(spread_r))]["date"], "rain_totals": totals,
        "wettest_model": max(totals, key=totals.get), "driest_model": min(totals, key=totals.get),
    }


def climate_stats(climate: dict[str, Any]) -> dict[str, Any]:
    annual = [a for a in climate.get("annual") or [] if a.get("mean_temp") is not None]
    if len(annual) < 10:
        return {}
    complete = annual[:-1]
    first, last = complete[:10], complete[-10:]
    mean = lambda rows, key: sum(r[key] for r in rows) / len(rows)
    warmest = max(complete, key=lambda a: a["mean_temp"])
    wettest = max(complete, key=lambda a: a["rain_total"])
    driest = min(complete, key=lambda a: a["rain_total"])
    return {
        "first_decade": f"{first[0]['year']}–{first[-1]['year']}", "last_decade": f"{last[0]['year']}–{last[-1]['year']}",
        "temp_change_c": round(mean(last, "mean_temp") - mean(first, "mean_temp"), 2), "rain_change_mm": round(mean(last, "rain_total") - mean(first, "rain_total")),
        "hot_days_first": round(mean(first, "hot_days_over_40"), 1), "hot_days_last": round(mean(last, "hot_days_over_40"), 1),
        "warmest_year": warmest["year"], "wettest_year": wettest["year"], "driest_year": driest["year"],
    }


async def workspace(lat: float, lon: float) -> dict[str, Any]:
    compare, climate, obs = await asyncio.gather(weather.compare_models(lat, lon), weather.climate(lat, lon), stations(lat, lon), return_exceptions=True)
    result: dict[str, Any] = {"generated": utcnow().isoformat(), "exports": list(EXPORTS)}
    result["models"] = None if isinstance(compare, Exception) else compare | {"stats": model_stats(compare)}
    result["climate"] = None if isinstance(climate, Exception) else climate | {"stats": climate_stats(climate)}
    result["stations"] = [] if isinstance(obs, Exception) else [{k: v for k, v in s.items() if k != "series"} | {"series": s["series"][-48:] if i == 0 else []} for i, s in enumerate(obs)]
    result["source"] = "Model runs from Open-Meteo (GFS, ECMWF IFS, ICON); climate from ERA5 reanalysis; station observations from IMD via WMO WIS 2.0 and airport METARs stored by WeatherGPT"
    return result


def _csv(header: list[str], rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


async def export(kind: str, lat: float, lon: float) -> str:
    if kind == "forecast":
        fc = await weather.forecast(lat, lon)
        keys = [k for k in fc["hourly"][0] if k not in ("time", "condition")]
        return _csv(["time", *keys], [[h["time"], *(h.get(k) for k in keys)] for h in fc["hourly"]])
    if kind == "models":
        compare = await weather.compare_models(lat, lon)
        models = list(compare["models"])
        header = ["date"] + [f"{m}_{v}" for m in models for v in ("tmax", "tmin", "rain", "gust")] + ["spread_tmax", "spread_rain"]
        return _csv(header, [[d["date"], *((d.get(m) or {}).get(v) for m in models for v in ("tmax", "tmin", "rain", "gust")), d.get("spread_tmax"), d.get("spread_rain")] for d in compare["days"]])
    if kind == "climate":
        climate = await weather.climate(lat, lon)
        return _csv(["year", "mean_temp_c", "rain_total_mm", "hot_days_over_40"], [[a["year"], a["mean_temp"], a["rain_total"], a["hot_days_over_40"]] for a in climate["annual"]])
    if kind == "observations":
        rows = []
        for s in await stations(lat, lon):
            for o in s["series"]:
                rows.append([s["station"], s["name"], s["lat"], s["lon"], s["km"], o["time"], o["temp_c"], o["dewpoint_c"], o["wind_kmh"], o["gust_kmh"], o["pressure_hpa"], o["weather"], o["raw"]])
        return _csv(["station", "name", "lat", "lon", "km", "time_utc", "temp_c", "dewpoint_c", "wind_kmh", "gust_kmh", "pressure_hpa", "weather", "raw"], rows)
    raise ValueError(f"Unknown export {kind}")
