import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import advisory, knowledge
from app.services import alerts as alert_service
from app.services import trips, weather

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class ChatContext:
    lat: float | None = None
    lon: float | None = None
    place_name: str | None = None
    place_label: str | None = None
    language: str = "en"
    profile: dict[str, Any] = field(default_factory=dict)
    cards: list[dict[str, Any]] = field(default_factory=list)
    profile_updates: list[dict[str, Any]] = field(default_factory=list)
    trip: dict[str, Any] | None = None


class ToolError(Exception):
    pass


def _is_screen_place(location: str, ctx: ChatContext) -> bool:
    wanted = location.strip().lower()
    names = {n.strip().lower() for n in (ctx.place_name, ctx.place_label) if n}
    return ctx.lat is not None and bool(names) and (wanted in names or wanted.split(",")[0].strip() in {n.split(",")[0] for n in names})


async def resolve_place(location: str | None, ctx: ChatContext) -> dict[str, Any]:
    if location and location.strip() and not _is_screen_place(location, ctx):
        query = location.strip()
        results = await weather.geocode(query, count=5)
        if not results and "," in query:
            head, _, rest = query.partition(",")
            results = await weather.geocode(head.strip(), count=10)
            region = rest.strip().lower()
            regional = [r for r in results if region and any(region.split(",")[-1].strip() in (r.get(k) or "").lower() for k in ("state", "district"))]
            results = regional or results
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
            }
            for d in fc["daily"][:7]
        ],
        "sunrise": (fc["daily"][0]["sunrise"] or "")[11:],
        "sunset": (fc["daily"][0]["sunset"] or "")[11:],
    }


async def _confidence(lat: float, lon: float) -> list[dict[str, Any]]:
    try:
        return weather.confidence(await weather.compare_models(lat, lon))
    except Exception:
        return []


async def get_forecast(ctx: ChatContext, location: str | None = None, model: str = "best_match") -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc, conf, observed = await asyncio.gather(
        weather.forecast(place["lat"], place["lon"], model=model),
        _confidence(place["lat"], place["lon"]),
        weather.nearest_observation(place["lat"], place["lon"]),
    )
    ctx.cards.append({"kind": "forecast", "place": place, "data": {**fc, "confidence": conf, "observed": observed}})
    compact = _compact_forecast(fc)
    if observed:
        compact["observed_now_at_nearest_station"] = {k: observed[k] for k in ("station", "name", "distance_km", "age_min", "temp_c", "humidity_pct", "wind_kmh", "weather")}
    by_date = {c["date"]: c for c in conf}
    for day in compact["daily"]:
        c = by_date.get(day["date"])
        if c:
            day["confidence"] = f"{c['label']} ({c['score']}/100, {c['rain_agreement']})"
    return {"place": _label(place), **compact}


async def get_alerts(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc = await weather.forecast(place["lat"], place["lon"])
    official = alert_service.alerts_for_place(await alert_service.official_alerts(), place)
    derived = alert_service.derived_advisories(fc)
    ctx.cards.append({"kind": "alerts", "place": place, "data": {"official": official, "derived": derived}})
    return {
        "place": _label(place),
        "official_imd_ndma_alerts": [
            {
                "event": a.get("event"),
                "severity": a.get("severity"),
                "headline": (a.get("headline") or "")[:220],
                "areas": a.get("areas", [])[:4],
                "expires": a.get("expires"),
                "match": a.get("match"),
            }
            for a in official[:5]
        ],
        "more_official_alerts": max(0, len(official) - 5),
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
    if data.get("available"):
        data = {**data, "decoded": advisory.decode_metar(data.get("raw_metar"))}
    ctx.cards.append({"kind": "aviation", "place": {"name": icao.upper()}, "data": data})
    return data


def _profile_crop(ctx: ChatContext, crop: str | None, stage: str | None) -> tuple[str | None, str | None]:
    if crop:
        return crop, stage
    crops = ctx.profile.get("crops") or []
    if crops:
        return crops[0].get("name"), stage or crops[0].get("stage")
    return None, stage


async def get_farm_advisory(ctx: ChatContext, location: str | None = None, crop: str | None = None, stage: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    crop, stage = _profile_crop(ctx, crop, stage)
    fc = await weather.forecast(place["lat"], place["lon"])
    data = advisory.farm_advisory(fc, crop, stage)
    ctx.cards.append({"kind": "farm", "place": place, "data": {**data, "hourly": fc["hourly"], "daily": fc["daily"][:7]}})
    return {"place": _label(place), **data}


async def get_fishing_advisory(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc, sea, feed = await asyncio.gather(
        weather.forecast(place["lat"], place["lon"]),
        weather.marine(place["lat"], place["lon"]),
        alert_service.official_alerts(),
    )
    data = advisory.fishing_advisory(sea, fc, alert_service.alerts_for_place(feed, place))
    ctx.cards.append({"kind": "fishing", "place": place, "data": data})
    return {"place": _label(place), **data}


async def get_city_advisory(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    place = await resolve_place(location, ctx)
    fc = await weather.forecast(place["lat"], place["lon"])
    data = advisory.urban_advisory(fc)
    ctx.cards.append({"kind": "urban", "place": place, "data": data})
    return {"place": _label(place), **{k: v for k, v in data.items() if k != "heat_series"}}


ROLES = ["general", "farmer", "fisher", "aviation", "urban", "disaster_manager", "researcher", "logistics"]


async def search_knowledge(ctx: ChatContext, query: str) -> dict[str, Any]:
    hits = await knowledge.search(query, k=5)
    if not hits:
        return {"results": [], "note": "No matching passage in the official document library."}
    ctx.cards.append({
        "kind": "sources",
        "place": {"name": "Official documents"},
        "data": {"query": query, "results": [{k: h[k] for k in ("title", "publisher", "url", "page", "text")} for h in hits]},
    })
    return {
        "results": [
            {"source": f"{h['publisher']} — {h['title']}" + (f", p.{h['page']}" if h["page"] else ""), "url": h["url"], "passage": h["text"][:900]}
            for h in hits
        ]
    }


async def update_profile(
    ctx: ChatContext,
    role: str | None = None,
    crops: list[dict[str, Any]] | None = None,
    save_place: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if role in ROLES:
        patch["role"] = role
    if crops:
        patch["crops"] = [
            {"name": advisory.normalize_crop(c.get("name")) or c.get("name"), "stage": c.get("stage") if c.get("stage") in advisory.STAGES else None}
            for c in crops
            if c.get("name")
        ]
    if save_place:
        results = await weather.geocode(save_place, count=1)
        if results:
            patch["save_place"] = results[0]
    if note:
        patch["note"] = note[:200]
    if patch:
        ctx.profile_updates.append(patch)
        ctx.profile = {**ctx.profile, **{k: v for k, v in patch.items() if k in ("role", "crops")}}
    return {"saved": patch or "nothing to save"}


async def plan_trip(ctx: ChatContext, destination: str, origin: str | None = None, mode: str = "car", depart: str | None = None, rest_stops: bool = False, via: list[str] | None = None) -> dict[str, Any]:
    start = await resolve_place(origin, ctx)
    end = await resolve_place(destination, ctx)
    stops = [await resolve_place(name, ctx) for name in (via or [])[:8] if name and name.strip()]
    when = None
    if depart:
        try:
            parsed = datetime.fromisoformat(depart)
            when = parsed if parsed.tzinfo else parsed.replace(tzinfo=IST)
        except ValueError:
            raise ToolError("depart must be an ISO date-time like 2026-09-28T06:00")
    try:
        trip = await trips.plan(start, end, mode if mode in trips.MODES else "car", when, bool(rest_stops), stops)
    except trips.TripError as exc:
        raise ToolError(str(exc)) from exc
    ctx.cards.append({"kind": "trip", "place": end, "data": trip | {"briefs": [trips.brief(trip, i) for i in range(len(trip["routes"]))]}})
    return trips.brief(trip)


async def assess_shipment(
    ctx: ChatContext, destination: str, origin: str | None = None, mode: str = "road", vehicle: str = "hcv", cargo: str = "general",
    depart: str | None = None, via: list[str] | None = None, two_drivers: bool = False,
) -> dict[str, Any]:
    from app.services import logistics

    start = await resolve_place(origin, ctx)
    request = {
        "origin": {"name": start.get("name"), "lat": start["lat"], "lon": start["lon"]}, "destination": {"name": destination},
        "vias": [{"name": name} for name in (via or [])[:8] if name and name.strip()],
        "mode": mode if mode in logistics.MODES else "road", "vehicle": vehicle if vehicle in logistics.VEHICLES else "hcv",
        "cargo": cargo if cargo in logistics.CARGO else "general", "crew": 2 if two_drivers else 1, "depart": depart or None,
    }
    try:
        result = await logistics.shipment(request)
    except trips.TripError as exc:
        raise ToolError(str(exc)) from exc
    route = result["routes"][0]
    packed = base64.urlsafe_b64encode(json.dumps(request | {"depart": route["depart"]}, ensure_ascii=False).encode()).decode().rstrip("=")
    ctx.cards.append({"kind": "shipment", "place": result["destination"], "data": {
        "origin": result["origin"]["name"], "destination": result["destination"]["name"], "mode": result["mode_label"], "vehicle": result["vehicle_label"], "cargo": result["cargo_label"],
        "verdict": route["verdict"], "arrive": route["arrive"], "distance_km": route["distance_km"], "delay_min": route["delay_min"], "delay_worst_min": route["delay_worst_min"],
        "risk": route["risk"]["label"], "confidence": route["confidence"]["label"], "report": f"/api/logistics/report.pdf?kind=shipment&q={packed}",
    }})
    return logistics.localise(logistics.brief(result)) | {"times": "All times are India Standard Time", "pdf": "A full PDF report can be downloaded from the card shown with this answer."}


async def get_freight_network(ctx: ChatContext) -> dict[str, Any]:
    from app.services import logistics

    try:
        board = await logistics.network()
    except trips.TripError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "summary": board["summary"], "vehicle": board["vehicle"],
        "lanes": [{k: lane[k] for k in ("name", "distance_km", "duration_min", "delay_min", "worst", "warning_count")} | {"risk": lane["risk"]["label"], "outlook": [{k: o[k] for k in ("hours", "delay_min", "risk")} for o in lane["outlook"]]} for lane in board["lanes"]],
    }


async def get_facility_outlook(ctx: ChatContext, kind: str = "all", name: str | None = None) -> dict[str, Any]:
    from app.services import logistics

    try:
        board = await logistics.facilities(kind if kind in ("all", "port", "airport", "hub") else "all")
    except trips.TripError as exc:
        raise ToolError(str(exc)) from exc
    sites = board["sites"]
    if name:
        needle = name.lower()
        sites = [s for s in sites if needle in s["name"].lower() or needle in (s.get("area") or "").lower() or needle == (s.get("code") or "").lower()] or sites
    else:
        sites = [s for s in sites if s["level"] >= 1] or sites[:6]
    return {
        "summary": board["summary"], "rules": board["rules"],
        "sites": [{k: s[k] for k in ("kind", "name", "area", "status", "now", "warnings", "cyclone")} | {"days": [{k: d[k] for k in ("date", "status", "lost_hours", "rain_mm", "gust_max", "vis_min", "wave_max", "reasons")} for d in s["days"]]} for s in sites[:10]],
    }


async def get_cyclones(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    from app.services import cyclones

    place = await resolve_place(location, ctx)
    return await cyclones.status_for_agent(place["lat"], place["lon"], _label(place))


async def get_lightning(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    from app.services import lightning

    place = await resolve_place(location, ctx)
    return await lightning.status_for_agent(place["lat"], place["lon"], _label(place))


async def get_forecast_accuracy(ctx: ChatContext, location: str | None = None) -> dict[str, Any]:
    from app.services import verify

    place = await resolve_place(location, ctx)
    return await verify.summary_for_agent(place["lat"], place["lon"], _label(place))


TOOL_FUNCTIONS = {
    "get_forecast": get_forecast,
    "get_alerts": get_alerts,
    "get_climate": get_climate,
    "compare_models": compare_models,
    "get_air_quality": get_air_quality,
    "get_marine": get_marine,
    "get_aviation": get_aviation,
    "get_farm_advisory": get_farm_advisory,
    "get_fishing_advisory": get_fishing_advisory,
    "get_city_advisory": get_city_advisory,
    "update_profile": update_profile,
    "search_knowledge": search_knowledge,
    "plan_trip": plan_trip,
    "assess_shipment": assess_shipment,
    "get_freight_network": get_freight_network,
    "get_facility_outlook": get_facility_outlook,
    "get_cyclones": get_cyclones,
    "get_lightning": get_lightning,
    "get_forecast_accuracy": get_forecast_accuracy,
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
        "name": "get_forecast_accuracy",
        "description": "How accurate the forecasts have been for this area over the last 10 days: each weather model (ECMWF, GFS, ICON, UK Met Office, JMA, Météo-France, GEM, CMA and WeatherGPT's own blend) is verified against METAR observations at the nearest IMD airport stations, with average temperature, dew point and wind errors, bias, and rain hit rate/false alarms/skill. Use when asked which model to trust, how reliable the forecast is, or about forecast accuracy or verification.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_lightning",
        "description": "Lightning and thunderstorms right now and in the next 36 hours: whether an official IMD/SDMA lightning or thunderstorm warning polygon covers the place and until when, live lightning strikes within 150 km in the last hour (nearest strike, counts within 10/20/30 km, storm movement and ETA), and the model thunderstorm outlook by hour. Use for lightning, thunder, 'is it safe to go out/work in the field', thunderstorm timing questions.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_cyclones",
        "description": "Tropical cyclones and depressions over the Bay of Bengal and Arabian Sea: live storms with position, IMD grade, forecast track, closest approach to the place, whether it is inside the forecast cone or gale zone, modelled storm surge, the IMD warning stage for that lead time, official IMD/JTWC outlooks, and the place's cyclone history since 1980 (how many storms passed within 150 km, when, how strong, which months). Use for any cyclone, depression, landfall, storm surge or cyclone season question.",
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
    {
        "name": "get_farm_advisory",
        "description": "Agro-met advisory for farmers: pesticide/fertiliser spray windows in the next 48 h, 7-day irrigation water balance (FAO-56 crop coefficient x ET0 minus effective rain), dry spells for harvest/drying, livestock heat stress (THI), heavy-rain days. Use for any farming, crop, sowing, spraying, irrigation, harvest or livestock question.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": _LOCATION,
                "crop": {"type": "STRING", "enum": list(advisory.CROP_KC), "description": "Crop, translated to one of the listed values (rice->paddy, chana/dal->pulses, tomato/onion->vegetables, bajra/ragi->millets). Omit to use the user's profile crop."},
                "stage": {"type": "STRING", "enum": list(advisory.STAGES), "description": "Crop growth stage if known."},
            },
        },
    },
    {
        "name": "get_fishing_advisory",
        "description": "Go / caution / no-go verdict for fishermen and small boats for now and the next 5 days from wave height, wind gusts and official sea/cyclone warnings. Location must be coastal.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "get_city_advisory",
        "description": "Urban advisory: heat index (feels-like) peak and band, waterlogging risk from rain intensity, and morning/evening commute weather. Use for city life, commute, outdoor work, school, events, heat or waterlogging questions.",
        "parameters": {"type": "OBJECT", "properties": {"location": _LOCATION}},
    },
    {
        "name": "update_profile",
        "description": "Remember facts the user states about themselves so future answers are tailored: their role, the crops they grow (with stage), a place to save, or a short note. Call it when the user tells you such a fact, together with any data tool needed to answer.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "role": {"type": "STRING", "enum": ROLES},
                "crops": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "name": {"type": "STRING", "enum": list(advisory.CROP_KC)},
                            "stage": {"type": "STRING", "enum": list(advisory.STAGES)},
                        },
                        "required": ["name"],
                    },
                },
                "save_place": {"type": "STRING", "description": "A place name the user wants saved, e.g. their village or farm location."},
                "note": {"type": "STRING", "description": "Short other fact worth remembering, e.g. 'owns a 5 m fibre boat'."},
            },
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search the official document library: IMD Standard Operating Procedures (forecasting & warning services, cyclone warnings, agromet advisories/GKMS, aviation met services), IMD RSMC cyclone terminology, IMD climate-health bulletin, and NDMA hazard guidance and Do's & Don'ts (heat wave, cold wave, cyclone, floods, urban floods, lightning, landslide, tsunami). Use it for definitions, official criteria and thresholds, what warnings and colour codes mean, how IMD services work, and safety/preparedness advice. Always write the query in English keywords.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": {"type": "STRING", "description": "Specific English keyword query in the vocabulary of IMD/NDMA documents, e.g. 'criteria for heat wave plains departure from normal', 'colour coding hazardous conditions green yellow orange red level', 'lightning safety crouch shelter 30/30 rule', 'warnings for fisheries criteria wind speed'."}},
            "required": ["query"],
        },
    },
    {
        "name": "assess_shipment",
        "description": "Freight and logistics: assess one shipment moving by road (truck), rail, air or coastal sea between two places. Returns a go, caution or hold verdict, the weather-adjusted arrival time and delay, hazards on each stretch at the time the load passes, official warnings and cyclones on the route, cargo exposure (cold chain, pharma, produce, moisture-sensitive, hazardous, livestock) and the best dispatch time in the next 48 hours. Use it for any truck, lorry, container, consignment, dispatch, delivery, fleet, cold chain or shipping question.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "destination": {"type": "STRING", "description": "Where the load is going: a city, port or hub, e.g. 'Mundra Port'."},
                "origin": {"type": "STRING", "description": "Where the load starts. Omit to use the place on the user's screen."},
                "via": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Places to pass through in order. Omit for a direct run."},
                "mode": {"type": "STRING", "enum": ["road", "rail", "air", "sea"], "description": "road (truck), rail, air or sea (coastal shipping between Indian ports)."},
                "vehicle": {"type": "STRING", "enum": ["lcv", "hcv", "container", "tanker", "reefer"], "description": "Road vehicle: lcv light truck, hcv heavy truck, container trailer, tanker or reefer (refrigerated)."},
                "cargo": {"type": "STRING", "enum": ["general", "chilled", "frozen", "pharma", "produce", "moisture", "electronics", "hazmat", "livestock"], "description": "Cargo type. chilled covers vaccines, insulin, dairy and anything kept at 2 to 8 °C; frozen is -18 °C or below; pharma is medicine kept at room temperature (15 to 25 °C); produce is fruit and vegetables without cooling; moisture means cement, grain, paper or textiles."},
                "depart": {"type": "STRING", "description": "Local dispatch date-time in ISO format, e.g. '2026-10-05T21:00'. Omit for now."},
                "two_drivers": {"type": "BOOLEAN", "description": "True when two drivers share the driving, so there is no overnight halt."},
            },
            "required": ["destination"],
        },
    },
    {
        "name": "get_freight_network",
        "description": "Live weather status of India's main road freight corridors (Delhi-Mumbai, Delhi-Kolkata, Mumbai-Chennai, Chennai-Kolkata and others): delay for a truck leaving now and in the next 48 hours, the worst hazard on each lane and official warnings crossing it. Use for questions about which lanes or corridors are disrupted or the overall freight picture.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_facility_outlook",
        "description": "Five-day operations outlook for Indian ports, large cargo airports and logistics hubs: hours of work likely to stop each day from wind, lightning, fog, heavy rain or waves, plus official warnings and cyclone threats. Use for questions about whether a port, airport or warehouse will be disrupted.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "enum": ["all", "port", "airport", "hub"], "description": "Which kind of facility."},
                "name": {"type": "STRING", "description": "Name, city or airport code to look for, e.g. 'Mundra', 'Chennai' or 'BOM'. Omit to list the facilities with problems."},
            },
        },
    },
    {
        "name": "plan_trip",
        "description": "Plan a journey and get the weather along the real route at the time the traveller will be at each point: rain, thunderstorms, fog, wind, heat or cold, official IMD/NDMA warnings along the way, the best time to leave, alternatives, and for flights the airport METARs and jet-level winds. Use it for any travel question between two places (road trip, bike ride, bus, train, flight, trek).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "destination": {"type": "STRING", "description": "Where the user is going, e.g. 'Hyderabad'."},
                "origin": {"type": "STRING", "description": "Where the trip starts. Omit to use the place on the user's screen."},
                "via": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Places to pass through on the way, in order, e.g. ['Nellore', 'Ongole']. Omit for a direct trip."},
                "mode": {"type": "STRING", "enum": ["car", "bike", "bus", "train", "flight", "trek"], "description": "car, bike (two-wheeler), bus, train, flight or trek (walking/hiking)."},
                "depart": {"type": "STRING", "description": "Local departure date-time in ISO format, e.g. '2026-09-28T06:00'. Omit for now."},
                "rest_stops": {"type": "BOOLEAN", "description": "True to suggest real rest stops (highway plazas, fuel stations, dhabas, hotels for overnight) for car or two-wheeler trips, when the user asks about breaks, food, fuel or where to stay."},
            },
            "required": ["destination"],
        },
    },
]
