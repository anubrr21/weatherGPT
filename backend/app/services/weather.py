import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from app.services.http import TTLCache, coord_key, get_retry
from app.services.wmo import compass, describe

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
METAR_URL = "https://aviationweather.gov/api/data/metar"

NWP_MODELS = {
    "best_match": "Best match (blended)",
    "gfs_seamless": "NOAA GFS",
    "ecmwf_ifs025": "ECMWF IFS 0.25°",
    "icon_seamless": "DWD ICON",
}

CURRENT_VARS = [
    "temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day", "precipitation",
    "weather_code", "cloud_cover", "pressure_msl", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "uv_index", "dew_point_2m",
]
HOURLY_VARS = [
    "temperature_2m", "apparent_temperature", "precipitation_probability", "precipitation",
    "weather_code", "wind_speed_10m", "wind_gusts_10m", "wind_direction_10m",
    "relative_humidity_2m", "cloud_cover", "visibility", "cape", "is_day", "uv_index",
]
DAILY_VARS = [
    "weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
    "precipitation_sum", "precipitation_probability_max", "precipitation_hours",
    "wind_speed_10m_max", "wind_gusts_10m_max", "wind_direction_10m_dominant",
    "uv_index_max", "sunrise", "sunset", "shortwave_radiation_sum", "et0_fao_evapotranspiration",
]

_forecast_cache = TTLCache(ttl_s=600)
_geo_cache = TTLCache(ttl_s=86400, max_items=2048)
_air_cache = TTLCache(ttl_s=1800)
_climate_cache = TTLCache(ttl_s=86400 * 3, max_items=256)
_marine_cache = TTLCache(ttl_s=1800)
_metar_cache = TTLCache(ttl_s=300)


async def geocode(query: str, count: int = 6) -> list[dict[str, Any]]:
    async def load() -> list[dict[str, Any]]:
        response = await get_retry(
            GEOCODE_URL, params={"name": query, "count": count, "language": "en", "format": "json"}
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        results.sort(key=lambda r: (r.get("country_code") != "IN", -(r.get("population") or 0)))
        return [
            {
                "name": r["name"],
                "district": r.get("admin2"),
                "state": r.get("admin1"),
                "country": r.get("country"),
                "country_code": r.get("country_code"),
                "lat": r["latitude"],
                "lon": r["longitude"],
                "elevation": r.get("elevation"),
                "timezone": r.get("timezone"),
            }
            for r in results
        ]

    return await _geo_cache.get_or_set(f"q:{query.strip().lower()}:{count}", load)


async def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        try:
            response = await get_retry(
                REVERSE_URL, params={"latitude": lat, "longitude": lon, "localityLanguage": "en"}
            )
            response.raise_for_status()
            data = response.json()
            admin = {a.get("adminLevel"): a.get("name") for a in data.get("localityInfo", {}).get("administrative", [])}
            return {
                "name": data.get("city") or data.get("locality") or admin.get(6) or f"{lat:.2f}, {lon:.2f}",
                "district": admin.get(5) or admin.get(6),
                "state": data.get("principalSubdivision"),
                "country": data.get("countryName"),
                "country_code": data.get("countryCode"),
                "lat": lat,
                "lon": lon,
            }
        except Exception:
            return {"name": f"{lat:.2f}°, {lon:.2f}°", "district": None, "state": None, "country": None,
                    "country_code": None, "lat": lat, "lon": lon}

    return await _geo_cache.get_or_set(coord_key(lat, lon, "rev"), load)


def _zip_series(block: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    times = block.get("time", [])
    return [{"time": t, **{k: block.get(k, [None] * len(times))[i] for k in keys}} for i, t in enumerate(times)]


async def forecast(lat: float, lon: float, model: str = "best_match", days: int = 10) -> dict[str, Any]:
    model = model if model in NWP_MODELS else "best_match"

    async def load() -> dict[str, Any]:
        response = await get_retry(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": ",".join(CURRENT_VARS),
                "hourly": ",".join(HOURLY_VARS),
                "daily": ",".join(DAILY_VARS),
                "timezone": "auto",
                "forecast_days": days,
                "models": model,
            },
        )
        response.raise_for_status()
        raw = response.json()
        current = raw.get("current", {})
        hourly = _zip_series(raw.get("hourly", {}), HOURLY_VARS)
        now_prefix = current.get("time", "")[:13]
        start = next((i for i, h in enumerate(hourly) if h["time"][:13] >= now_prefix), 0)
        daily = _zip_series(raw.get("daily", {}), DAILY_VARS)
        for d in daily:
            d["condition"] = describe(d["weather_code"])
        for h in hourly:
            h["condition"] = describe(h["weather_code"])
        return {
            "model": model,
            "model_name": NWP_MODELS[model],
            "timezone": raw.get("timezone"),
            "utc_offset_seconds": raw.get("utc_offset_seconds"),
            "elevation": raw.get("elevation"),
            "current": {
                **current,
                "condition": describe(current.get("weather_code")),
                "wind_compass": compass(current.get("wind_direction_10m")),
            },
            "hourly": hourly[start:start + 48],
            "daily": daily,
        }

    return await _forecast_cache.get_or_set(coord_key(lat, lon, model, days), load)


async def compare_models(lat: float, lon: float, days: int = 7) -> dict[str, Any]:
    models = [m for m in NWP_MODELS if m != "best_match"]

    async def load() -> dict[str, Any]:
        response = await get_retry(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max",
                "timezone": "auto",
                "forecast_days": days,
                "models": ",".join(models),
            },
        )
        response.raise_for_status()
        daily = response.json().get("daily", {})
        rows = []
        for i, day in enumerate(daily.get("time", [])):
            row: dict[str, Any] = {"date": day}
            for m in models:
                row[m] = {
                    "tmax": daily.get(f"temperature_2m_max_{m}", [None])[i],
                    "tmin": daily.get(f"temperature_2m_min_{m}", [None])[i],
                    "rain": daily.get(f"precipitation_sum_{m}", [None])[i],
                    "gust": daily.get(f"wind_gusts_10m_max_{m}", [None])[i],
                }
            tmaxes = [row[m]["tmax"] for m in models if row[m]["tmax"] is not None]
            rains = [row[m]["rain"] for m in models if row[m]["rain"] is not None]
            row["spread_tmax"] = round(max(tmaxes) - min(tmaxes), 1) if tmaxes else None
            row["spread_rain"] = round(max(rains) - min(rains), 1) if rains else None
            rows.append(row)
        return {"models": {m: NWP_MODELS[m] for m in models}, "days": rows}

    return await _forecast_cache.get_or_set(coord_key(lat, lon, "compare", days), load)


PM25_BREAKS = [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)]
PM10_BREAKS = [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200), (251, 350, 201, 300), (351, 430, 301, 400), (431, 800, 401, 500)]
NAQI_BANDS = [(50, "Good"), (100, "Satisfactory"), (200, "Moderate"), (300, "Poor"), (400, "Very Poor"), (500, "Severe")]


def _sub_index(value: float | None, breaks: list[tuple[int, int, int, int]]) -> int | None:
    if value is None:
        return None
    for lo, hi, ilo, ihi in breaks:
        if value <= hi:
            return round(ilo + (ihi - ilo) * (max(value, lo) - lo) / max(hi - lo, 1))
    return 500


async def air_quality(lat: float, lon: float) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        response = await get_retry(
            AIR_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "pm2_5,pm10,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,us_aqi,dust",
                "hourly": "pm2_5,pm10",
                "past_days": 1,
                "forecast_days": 1,
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        raw = response.json()
        current = raw.get("current", {})
        hourly = raw.get("hourly", {})
        pm25_24 = [v for v in (hourly.get("pm2_5") or [])[-48:-24] if v is not None]
        pm10_24 = [v for v in (hourly.get("pm10") or [])[-48:-24] if v is not None]
        pm25_avg = mean(pm25_24) if pm25_24 else current.get("pm2_5")
        pm10_avg = mean(pm10_24) if pm10_24 else current.get("pm10")
        subs = {"pm2_5": _sub_index(pm25_avg, PM25_BREAKS), "pm10": _sub_index(pm10_avg, PM10_BREAKS)}
        valid = [v for v in subs.values() if v is not None]
        naqi = max(valid) if valid else None
        band = next((label for limit, label in NAQI_BANDS if naqi is not None and naqi <= limit), None)
        return {
            "current": current,
            "india_naqi": naqi,
            "india_naqi_band": band,
            "dominant": max(subs, key=lambda k: subs[k] or -1) if valid else None,
            "pm2_5_24h_avg": round(pm25_avg, 1) if pm25_avg is not None else None,
            "pm10_24h_avg": round(pm10_avg, 1) if pm10_avg is not None else None,
        }

    return await _air_cache.get_or_set(coord_key(lat, lon, "air"), load)


def _trend_per_decade(xs: list[int], ys: list[float]) -> float | None:
    if len(xs) < 5:
        return None
    mx, my = mean(xs), mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom * 10, 3)


async def climate(lat: float, lon: float, month: int | None = None, start_year: int = 1991) -> dict[str, Any]:
    today = date.today()
    month = month or today.month
    end = today - timedelta(days=7)

    async def load() -> dict[str, Any]:
        response = await get_retry(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": f"{start_year}-01-01",
                "end_date": end.isoformat(),
                "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,precipitation_sum",
                "timezone": "auto",
            },
            timeout=60,
        )
        response.raise_for_status()
        daily = response.json().get("daily", {})
        years: dict[int, dict[str, list[float]]] = {}
        month_years: dict[int, dict[str, list[float]]] = {}
        for i, day in enumerate(daily.get("time", [])):
            y, m = int(day[:4]), int(day[5:7])
            tmean = daily["temperature_2m_mean"][i]
            tmax = daily["temperature_2m_max"][i]
            rain = daily["precipitation_sum"][i]
            bucket = years.setdefault(y, {"t": [], "tmax": [], "rain": []})
            if tmean is not None:
                bucket["t"].append(tmean)
            if tmax is not None:
                bucket["tmax"].append(tmax)
            if rain is not None:
                bucket["rain"].append(rain)
            if m == month:
                mb = month_years.setdefault(y, {"t": [], "tmax": [], "rain": []})
                if tmean is not None:
                    mb["t"].append(tmean)
                if tmax is not None:
                    mb["tmax"].append(tmax)
                if rain is not None:
                    mb["rain"].append(rain)

        full_years = [y for y, b in years.items() if len(b["t"]) >= 360]
        annual = [
            {
                "year": y,
                "mean_temp": round(mean(years[y]["t"]), 2),
                "hot_days_over_40": sum(1 for v in years[y]["tmax"] if v >= 40),
                "rain_total": round(sum(years[y]["rain"]), 1),
            }
            for y in sorted(full_years)
        ]
        monthly = [
            {"year": y, "mean_temp": round(mean(b["t"]), 2), "rain_total": round(sum(b["rain"]), 1)}
            for y, b in sorted(month_years.items())
            if len(b["t"]) >= 25
        ]
        normal_years = [r for r in monthly if 1991 <= r["year"] <= 2020]
        return {
            "period": f"{start_year}–{end.year}",
            "source": "ERA5 reanalysis via Open-Meteo archive",
            "annual": annual,
            "annual_temp_trend_c_per_decade": _trend_per_decade(
                [r["year"] for r in annual], [r["mean_temp"] for r in annual]
            ),
            "annual_rain_trend_mm_per_decade": _trend_per_decade(
                [r["year"] for r in annual], [r["rain_total"] for r in annual]
            ),
            "month": month,
            "month_by_year": monthly,
            "month_normal_1991_2020": {
                "mean_temp": round(mean(r["mean_temp"] for r in normal_years), 2) if normal_years else None,
                "rain_total": round(mean(r["rain_total"] for r in normal_years), 1) if normal_years else None,
            },
        }

    return await _climate_cache.get_or_set(coord_key(lat, lon, "climate", month, start_year, end.isoformat()), load)


async def marine(lat: float, lon: float) -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        response = await get_retry(
            MARINE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "wave_height,wave_direction,wave_period,swell_wave_height,sea_surface_temperature",
                "daily": "wave_height_max,wave_period_max,swell_wave_height_max",
                "timezone": "auto",
                "forecast_days": 5,
            },
        )
        if response.status_code == 400:
            return {"available": False, "reason": "No marine data for this point (likely inland)."}
        response.raise_for_status()
        raw = response.json()
        current = raw.get("current", {})
        if current.get("wave_height") is None:
            return {"available": False, "reason": "No marine data for this point (likely inland)."}
        return {
            "available": True,
            "current": current,
            "daily": _zip_series(raw.get("daily", {}), ["wave_height_max", "wave_period_max", "swell_wave_height_max"]),
        }

    return await _marine_cache.get_or_set(coord_key(lat, lon, "marine"), load)


async def metar(icao: str) -> dict[str, Any]:
    code = icao.strip().upper()

    async def load() -> dict[str, Any]:
        response = await get_retry(METAR_URL, params={"ids": code, "format": "json", "taf": "true", "hours": 3})
        response.raise_for_status()
        rows = response.json() if response.content else []
        if not rows:
            return {"station": code, "available": False}
        latest = rows[0]
        return {
            "station": code,
            "available": True,
            "name": latest.get("name"),
            "raw_metar": latest.get("rawOb"),
            "raw_taf": latest.get("rawTaf"),
            "observed": latest.get("reportTime"),
            "temp_c": latest.get("temp"),
            "dewpoint_c": latest.get("dewp"),
            "wind_dir": latest.get("wdir"),
            "wind_kt": latest.get("wspd"),
            "gust_kt": latest.get("wgst"),
            "visibility": latest.get("visib"),
            "altimeter_hpa": latest.get("altim"),
            "flight_category": latest.get("fltCat"),
            "clouds": latest.get("clouds"),
        }

    return await _metar_cache.get_or_set(f"metar:{code}", load)


def confidence(compare: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for i, day in enumerate(compare["days"]):
        spread_t = day.get("spread_tmax") or 0
        spread_r = min(day.get("spread_rain") or 0, 40)
        rains = [day[m]["rain"] for m in compare["models"] if day[m]["rain"] is not None]
        wet_votes = sum(1 for r in rains if r >= 2.5)
        rain_split = 0 < wet_votes < len(rains)
        score = 100 - i * 5 - spread_t * 7 - spread_r * 1.1 - (12 if rain_split else 0)
        score = int(max(5, min(100, round(score))))
        out.append({
            "date": day["date"],
            "score": score,
            "label": "High" if score >= 75 else "Medium" if score >= 50 else "Low",
            "spread_tmax": day.get("spread_tmax"),
            "spread_rain": day.get("spread_rain"),
            "rain_agreement": f"{wet_votes}/{len(rains)} models expect ≥2.5 mm",
        })
    return out


_obs_cache = TTLCache(ttl_s=300)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


async def nearest_observation(lat: float, lon: float, max_km: float = 120) -> dict[str, Any] | None:
    async def load() -> dict[str, Any] | None:
        box = f"{lat - 1.2:.2f},{lon - 1.2:.2f},{lat + 1.2:.2f},{lon + 1.2:.2f}"
        response = await get_retry(METAR_URL, params={"bbox": box, "format": "json"})
        if response.status_code != 200 or not response.content.strip():
            return None
        rows = [r for r in response.json() if r.get("lat") is not None and r.get("temp") is not None]
        if not rows:
            return None
        best = min(rows, key=lambda r: _km(lat, lon, r["lat"], r["lon"]))
        distance = _km(lat, lon, best["lat"], best["lon"])
        if distance > max_km:
            return None
        observed = best.get("reportTime") or best.get("obsTime")
        age_min = None
        if isinstance(observed, str):
            try:
                age_min = round((datetime.now(timezone.utc) - datetime.fromisoformat(observed.replace("Z", "+00:00"))).total_seconds() / 60)
            except ValueError:
                age_min = None
        dew = best.get("dewp")
        temp = best["temp"]
        rh = round(100 * math.exp(17.625 * dew / (243.04 + dew)) / math.exp(17.625 * temp / (243.04 + temp))) if dew is not None else None
        return {
            "station": best.get("icaoId"),
            "name": best.get("name"),
            "distance_km": round(distance),
            "age_min": age_min,
            "temp_c": temp,
            "dewpoint_c": dew,
            "humidity_pct": rh,
            "wind_kmh": round(best["wspd"] * 1.852) if best.get("wspd") is not None else None,
            "wind_dir": best.get("wdir"),
            "visibility": best.get("visib"),
            "pressure_hpa": best.get("altim"),
            "weather": best.get("wxString"),
            "raw": best.get("rawOb"),
            "source": "METAR via aviationweather.gov (real station observation)",
        }

    try:
        return await _obs_cache.get_or_set(coord_key(lat, lon, "obs"), load)
    except Exception:
        return None
