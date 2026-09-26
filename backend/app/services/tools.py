from dataclasses import dataclass, field
from typing import Any

from app.services import alerts as alert_service
from app.services import weather


@dataclass
class ChatContext:
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = None
    language: str = "en"
    cards: list[dict[str, Any]] = field(default_factory=list)


class ToolError(Exception):
    pass


async def resolve_place(location: str | None, ctx: ChatContext) -> dict[str, Any]:
    if location and location.strip():
        results = await weather.geocode(location.strip(), count=5)
        if not results:
            raise ToolError(f"Could not find a place called '{location}'.")
        return results[0]
    if ctx.lat is None or ctx.lon is None:
        raise ToolError("No location given and device location is unavailable. Ask the user which place they mean.")
    place = await weather.reverse_geocode(ctx.lat, ctx.lon)
    if ctx.place_name:
        place = {**place, "name": ctx.place_name}
    return place


def _label(place: dict[str, Any]) -> str:
    parts = [place.get("name"), place.get("district") if place.get("district") != place.get("name") else None, place.get("state")]
    return ", ".join(p for p in parts if p)


def _compact_forecast(fc: dict[str, Any]) -> dict[str, Any]:
    c = fc["current"]
    return {
        "model": fc["model_name"],
        "timezone": fc["timezone"],
        "now": {
            "time": c.get("time"),
            "condition": c["condition"]["label"],
            "temp_c": c.get("temperature_2m"),
            "feels_like_c": c.get("apparent_temperature"),
            "humidity_pct": c.get("relative_humidity_2m"),
            "dew_point_c": c.get("dew_point_2m"),
            "wind_kmh": c.get("wind_speed_10m"),
            "gust_kmh": c.get("wind_gusts_10m"),
            "wind_from": c.get("wind_compass"),
            "pressure_hpa": c.get("pressure_msl"),
            "cloud_pct": c.get("cloud_cover"),
            "uv": c.get("uv_index"),
            "precip_mm": c.get("precipitation"),
        },
        "next_24h_every_3h": [
            {
                "time": h["time"][11:16],
                "temp_c": h["temperature_2m"],
                "rain_prob_pct": h["precipitation_probability"],
                "rain_mm": h["precipitation"],
                "gust_kmh": h["wind_gusts_10m"],
                "condition": h["condition"]["label"],
            }
            for h in fc["hourly"][:24:3]
        ],
        "daily": [
            {
                "date": d["time"],
                "condition": d["condition"]["label"],
                "tmax_c": d["temperature_2m_max"],
                "tmin_c": d["temperature_2m_min"],
                "rain_mm": d["precipitation_sum"],
                "rain_prob_pct": d["precipitation_probability_max"],
                "gust_kmh": d["wind_gusts_10m_max"],
                "uv_max": d["uv_index_max"],
                "et0_mm": d["et0_fao_evapotranspiration"],
                "sunrise": (d["sunrise"] or "")[11:],
                "sunset": (d["sunset"] or "")[11:],
            }
            for d in fc["daily"][:7]
        ],
    }


async def get_forecast(ctx: ChatContext, location: str | None = None, model: str = "best_match") -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc = await weather.forecast(place["lat"], place["lon"], model=model)
    ctx.cards.append({"kind": "forecast", "place": place, "data": fc})
    return {"place": _label(place), **_compact_forecast(fc)}


async def get_alerts(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc = await weather.forecast(place["lat"], place["lon"])
    official = alert_service.alerts_for_place(await alert_service.official_alerts(), place)
    derived = alert_service.derived_advisories(fc)
    ctx.cards.append({"kind": "alerts", "place": place, "data": {"official": official, "derived": derived}})
    return {
        "place": _label(place),
        "official_imd_ndma_alerts": [
            {k: a.get(k) for k in ("event", "severity", "urgency", "headline", "areas", "expires", "issuer", "instruction", "match")}
            for a in official[:8]
        ],
        "model_derived_advisories": derived,
    }


async def get_climate(ctx: ChatContext, location: str | None = None, month: int | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    data = await weather.climate(place["lat"], place["lon"], month=month)
    ctx.cards.append({"kind": "climate", "place": place, "data": data})
    recent = data["month_by_year"][-5:]
    return {
        "place": _label(place),
        "period": data["period"],
        "source": data["source"],
        "annual_temp_trend_c_per_decade": data["annual_temp_trend_c_per_decade"],
        "annual_rain_trend_mm_per_decade": data["annual_rain_trend_mm_per_decade"],
        "first_5_years_annual": data["annual"][:5],
        "last_5_years_annual": data["annual"][-5:],
        "month": data["month"],
        "month_normal_1991_2020": data["month_normal_1991_2020"],
        "month_last_5_years": recent,
    }


async def compare_models(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    data = await weather.compare_models(place["lat"], place["lon"])
    ctx.cards.append({"kind": "models", "place": place, "data": data})
    return {"place": _label(place), **data}


async def get_air_quality(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    data = await weather.air_quality(place["lat"], place["lon"])
    ctx.cards.append({"kind": "air", "place": place, "data": data})
    return {"place": _label(place), **data}


async def get_marine(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    data = await weather.marine(place["lat"], place["lon"])
    ctx.cards.append({"kind": "marine", "place": place, "data": data})
    return {"place": _label(place), **data}


async def get_aviation(ctx: ChatContext, icao: str) -> dict[str, Any]:
    data = await weather.metar(icao)
    ctx.cards.append({"kind": "aviation", "place": {"name": icao.upper()}, "data": data})
    return data


TOOL_FUNCTIONS = {
    "get_forecast": get_forecast,
    "get_alerts": get_alerts,
    "get_climate": get_climate,
    "compare_models": compare_models,
    "get_air_quality": get_air_quality,
    "get_marine": get_marine,
    "get_aviation": get_aviation,
}

_LOCATION = {
    "type": "STRING",
    "description": "Place name in English (city, town, village or district, optionally with state), e.g. 'Guntur, Andhra Pradesh'. Omit to use the user's current device location.",
}

TOOL_DECLARATIONS = [
    {
        "name": "get_forecast",
        "description": "Current conditions, next 48 h hourly and 10-day daily forecast from numerical weather prediction models. Use for any question about present or future weather, rain, temperature, wind, humidity, UV, sunrise/sunset, farming/irrigation timing, travel or event planning.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": _LOCATION,
                "model": {
                    "type": "STRING",
                    "enum": list(weather.NWP_MODELS),
                    "description": "NWP model. Default best_match. Use gfs_seamless, ecmwf_ifs025 or icon_seamless only if the user asks for a specific model.",
                },
            },
        },
    },
    {
        "name": "get_alerts",
        "description": "Official live IMD/NDMA CAP warnings for the place plus model-derived advisories (heavy rain, heat wave, cold wave, strong winds, thunderstorm, fog) computed with IMD thresholds. Use for any safety, warning, cyclone, flood, storm or 'is it safe' question.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_climate",
        "description": "Historical climate analysis since 1991 from ERA5 reanalysis: annual mean temperature trend, rainfall trend, hot days above 40 °C, and a chosen month compared with the 1991–2020 normal. Use for climate change, 'is this normal', historical or trend questions.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": _LOCATION,
                "month": {"type": "INTEGER", "description": "Month number 1-12 to analyse. Defaults to the current month."},
            },
        },
    },
    {
        "name": "compare_models",
        "description": "Compare 7-day daily forecasts from NOAA GFS, ECMWF IFS and DWD ICON side by side with the spread between them. Use when the user asks about forecast confidence, uncertainty, or different models.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_air_quality",
        "description": "Current air pollution with India's CPCB National AQI computed from 24 h PM2.5/PM10 averages, plus pollutant concentrations.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_marine",
        "description": "Sea state for coastal/marine users: wave height, swell, wave period, sea surface temperature and 5-day max waves. Use for fishermen, boats, ports, beach questions. The location should be a coastal place.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_aviation",
        "description": "Latest METAR observation and TAF for an airport, for aviation weather briefings. Needs the ICAO code, e.g. VIDP Delhi, VABB Mumbai, VOBL Bengaluru, VOMM Chennai, VECC Kolkata, VOHS Hyderabad, VOBZ Vijayawada.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"icao": {"type": "STRING", "description": "4-letter ICAO airport code."}},
            "required": ["icao"],
        },
    },
]
