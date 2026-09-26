import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, AsyncIterator

from app.services import advisory, providers, tools

MAX_TOOL_ROUNDS = 5
MAX_CAPACITY_WAIT_S = 20

log = logging.getLogger("weathergpt.agent")

LANGUAGES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "te": "Telugu", "ta": "Tamil", "mr": "Marathi",
    "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "or": "Odia", "pa": "Punjabi", "as": "Assamese",
    "ur": "Urdu",
}

TOOL_STATUS = {
    "get_forecast": "Pulling NWP forecast",
    "get_alerts": "Checking IMD / NDMA warnings",
    "get_climate": "Crunching 30+ years of ERA5 climate data",
    "compare_models": "Comparing GFS · ECMWF · ICON",
    "get_air_quality": "Reading air quality sensors",
    "get_marine": "Reading sea state",
    "get_aviation": "Fetching METAR / TAF",
    "get_farm_advisory": "Computing agro-met advisory",
    "get_fishing_advisory": "Assessing sea for small boats",
    "get_city_advisory": "Computing heat index & waterlogging",
    "update_profile": "Remembering that",
}


def _profile_text(profile: dict[str, Any]) -> str:
    parts = []
    if profile.get("role") and profile["role"] != "general":
        parts.append(f"role: {profile['role'].replace('_', ' ')}")
    crops = [f"{c.get('name')}{' (' + c['stage'] + ' stage)' if c.get('stage') else ''}" for c in profile.get("crops") or [] if c.get("name")]
    if crops:
        parts.append("crops: " + ", ".join(crops))
    places = [p.get("name") for p in profile.get("places") or [] if p.get("name")]
    if places:
        parts.append("saved places: " + ", ".join(places[:6]))
    notes = [n for n in profile.get("notes") or [] if n]
    if notes:
        parts.append("notes: " + "; ".join(notes[-5:]))
    return "; ".join(parts) if parts else "nothing known yet"


def system_prompt(ctx: tools.ChatContext) -> str:
    language = LANGUAGES.get(ctx.language, "English")
    where = (
        f"The user's device is at lat {ctx.lat:.4f}, lon {ctx.lon:.4f}" + (f" ({ctx.place_name})" if ctx.place_name else "")
        if ctx.lat is not None and ctx.lon is not None
        else "The user's device location is unknown"
    )
    return f"""You are WeatherGPT, a meteorological assistant for India built on live data: NWP models (GFS, ECMWF, ICON), official IMD/NDMA CAP warnings, ERA5 climate reanalysis, CPCB-style AQI, marine and METAR data.

Current local date-time: {datetime.now().strftime('%A %d %B %Y, %H:%M')}. {where}.
What you know about this user: {_profile_text(ctx.profile)}.

Rules:
- Always call tools for real data. Never invent numbers. If a tool fails, say so plainly.
- Reply in {language} unless the user clearly writes in another language; then reply in that language. Use the native script. Keep place names recognisable.
- Be concise and actionable: lead with the direct answer, then key numbers, then practical advice. Short paragraphs or tight bullet points; no tables (the app renders rich cards from tool data next to your reply).
- Tailor advice to the user's role and crops. Use the sector tools: get_farm_advisory for farmers (give concrete spray windows with times, irrigate/hold with mm, harvest/drying days), get_fishing_advisory for fishermen (lead with GO / CAUTION / NO-GO), get_aviation for pilots (decoded briefing: flight category, wind, visibility, cloud, hazards, trend), get_city_advisory for urban users (heat index, waterlogging, commute), get_alerts for disaster managers (severity, timing, affected areas, actions).
- When the user states a lasting fact about themselves (their job, crops and stage, village, boat), call update_profile as well, then answer. Do not announce that you saved it unless asked.
- Each forecast day carries a confidence label with a 0–100 score (not a percentage of agreement) and how many of the 3 models expect ≥2.5 mm rain. Mention it when the answer depends on uncertain rain or days beyond tomorrow.
- Answer rain questions calibrated to the numbers: say rain is likely only when the day's rain is ≥2.5 mm or the chance is ≥60%; for under 1 mm or a chance under 40%, say rain is unlikely or only a brief trace is possible. Never say "yes, it will rain" for trace amounts.
- Tool data contains English condition labels such as "Light drizzle"; translate them into the reply language.
- For safety questions, prioritise official IMD/NDMA warnings and clearly distinguish them from model-derived advisories. Include specific protective actions.
- Express uncertainty honestly: forecasts beyond 3 days are less reliable; mention model disagreement when relevant.
- Temperatures in °C, rain in mm, wind in km/h (knots for aviation).

Reply format (strict):
1. After you have the data, START the reply with a spoken version wrapped exactly as <speak>...</speak>. It is read aloud by a voice, so write it the way a friendly local weather presenter would talk to this person: 1 to 3 short sentences in the reply language, answering only what was asked, most important fact first, with one practical tip if useful. No markdown, bullets, symbols, units written as symbols, decimals, dates in digits or English words inside other languages. Round numbers and say units as spoken words in that language (for example "about 33 degrees", "around 20 kilometres an hour", "a light chance of rain"). Do not greet or repeat the question.
2. Then the written answer for the screen, following the rules above."""


async def _run_tool(name: str, args: dict[str, Any], ctx: tools.ChatContext) -> dict[str, Any]:
    fn = tools.TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Unknown tool {name}"}
    try:
        return await fn(ctx, **args)
    except tools.ToolError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"Data source failed: {type(exc).__name__}: {exc}"}


def _event(kind: str, **data: Any) -> dict[str, Any]:
    return {"type": kind, **data}


async def run_provider(provider: providers.Provider, ctx: tools.ChatContext) -> AsyncIterator[dict[str, Any]]:
    wrote = False
    for _ in range(MAX_TOOL_ROUNDS):
        calls: list[providers.Call] = []
        async for kind, value in provider.turn():
            if kind == "text":
                wrote = wrote or bool(value.strip())
                yield _event("delta", text=value)
            else:
                calls.append(value)
        if not calls:
            if not wrote:
                raise providers.ProviderError(f"{provider.label} returned an empty answer")
            return
        for call in calls:
            yield _event("status", text=TOOL_STATUS.get(call.name, call.name), tool=call.name, args=call.args)
        before = len(ctx.cards)
        updates_before = len(ctx.profile_updates)
        results = await asyncio.gather(*(_run_tool(c.name, c.args, ctx) for c in calls))
        for card in ctx.cards[before:]:
            yield _event("card", card=card)
        for patch in ctx.profile_updates[updates_before:]:
            yield _event("profile", patch=patch)
        provider.add_results(calls, list(results))
    yield _event("delta", text="\n\n(Stopped after too many data lookups.)")


INTENTS = [
    ("get_farm_advisory", r"spray|pesticide|fertili|irrigat|crop|farm|sow|harvest|paddy|wheat|cotton|kisan|khet|छिड़क|सिंचाई|फसल|किसान|धान|పంట|పిచికారీ|பயிர்|ফসল"),
    ("get_fishing_advisory", r"fisher|fishing|boat|venture|मछु|नाव|మత్స్య|పడవ|மீன்|படகு|মাছ"),
    ("get_city_advisory", r"commute|office|waterlog|traffic|heat index|feels like|school|outdoor|jalbhar|जलभराव"),
    ("get_alerts", r"alert|warn|cyclone|flood|storm|safe|danger|चेतावनी|तूफान|बाढ़|హెచ్చరిక|எச்சரிக்கை|সতর্ক"),
    ("get_climate", r"climate|trend|histor|normal|hotter|warmer|\d+ years|past years|last year|जलवायु|ఇతిహాస|காலநிலை"),
    ("compare_models", r"model|gfs|ecmwf|icon|confiden|uncertain"),
    ("get_air_quality", r"aqi|air quality|pollution|pm2|smog|प्रदूषण"),
    ("get_marine", r"sea|wave|marine|tide|समुद्र"),
]


NOT_PLACES = re.compile(
    r"^(the|my|our|this|that|here|there|today|tomorrow|tonight|now|next|coming|few|some|all|a|an|week|weekend|days?|hours?|morning|evening)\b",
    re.I,
)


def _extract_location(message: str) -> str | None:
    tail = re.compile(r"([A-Za-z][A-Za-z .'-]{2,40}?)(?:\s+(?:today|tomorrow|now|this|next|tonight|on|during|weather|and|to|in|for)\b|[?.!,]|$)", re.I)
    for prep in re.finditer(r"\b(?:in|at|for|near|of|from|around)\s+", message, re.I):
        match = tail.match(message, prep.end())
        if match and not NOT_PLACES.match(match.group(1).strip()):
            return match.group(1).strip()
    return None


def _say(value: float | None) -> str:
    return "unknown" if value is None else str(round(value))


def _offline_speech(name: str, result: dict[str, Any]) -> str | None:
    if "error" in result:
        return None
    place = (result.get("place") or "").split(",")[0]
    if name == "get_forecast":
        n = result["now"]
        tomorrow = result["daily"][1] if len(result["daily"]) > 1 else result["daily"][0]
        prob = tomorrow.get("rain_prob_pct") or 0
        rain = "rain looks likely" if (tomorrow.get("rain_mm") or 0) >= 2.5 or prob >= 60 else "rain is unlikely" if prob < 40 else "there is a small chance of rain"
        return (
            f"Right now in {place} it's about {_say(n['temp_c'])} degrees and {n['condition'].lower()}. "
            f"Tomorrow, {rain}, with temperatures between {_say(tomorrow['tmin_c'])} and {_say(tomorrow['tmax_c'])} degrees."
        )
    if name == "get_alerts":
        official = result["official_imd_ndma_alerts"]
        if official:
            return f"There {'is an official warning' if len(official) == 1 else f'are {len(official)} official warnings'} for the {place} area. The main one is {official[0]['event'] or 'a weather alert'}. Please check the details on screen."
        if result["model_derived_advisories"]:
            return f"There are no official warnings for {place}, but the forecast flags {result['model_derived_advisories'][0]['event'].lower()} in the coming days."
        return f"Good news, there are no weather warnings for {place} right now."
    if name == "get_farm_advisory":
        w = result["spray"]["windows"]
        irr = result["irrigation"]
        if w:
            start = datetime.fromisoformat(w[0]["start"])
            day = "today" if start.date() == datetime.now().date() else start.strftime("%A")
            spray = f"The next good time to spray is {day} from {start.strftime('%I').lstrip('0')} {'in the morning' if start.hour < 12 else 'in the afternoon' if start.hour < 17 else 'in the evening'}, for about {w[0]['hours']} hours."
        else:
            spray = "There's no safe spraying window in the next two days."
        water = "You should irrigate this week." if irr["deficit_mm"] > 20 else "Expected rain should cover your crop's water need."
        return f"{spray} {water}"
    if name == "get_fishing_advisory":
        verdict = {"GO": "it's safe to go out", "CAUTION": "go out only with caution", "NO-GO": "please do not go to sea"}[result["now"]]
        return f"Right now at {place}, {verdict}. Winds are gusting to about {_say(result['gust_now_kmh'])} kilometres an hour."
    if name == "get_city_advisory":
        peak = result["heat_index_peak"]
        return f"In {place} it will feel like about {_say(peak['heat_index'])} degrees at its hottest, around {int(peak['time'][11:13])} o'clock. Waterlogging risk is {result['waterlogging_risk']}."
    if name == "get_air_quality":
        return f"Air quality in {place} is {(result.get('india_naqi_band') or 'unknown').lower()}, with an AQI of about {_say(result.get('india_naqi'))}."
    return None


def _offline_summary(name: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return result["error"]
    place = result.get("place", "")
    if name == "get_forecast":
        n = result["now"]
        today = result["daily"][0]
        tomorrow = result["daily"][1] if len(result["daily"]) > 1 else today
        return (
            f"**{place}** — {n['condition']}, {n['temp_c']} °C (feels {n['feels_like_c']} °C), humidity {n['humidity_pct']}%, "
            f"wind {n['wind_kmh']} km/h from {n['wind_from']}.\n\n"
            f"Today: {today['tmin_c']}–{today['tmax_c']} °C, rain {today['rain_mm']} mm ({today['rain_prob_pct']}% chance).\n"
            f"Tomorrow: {tomorrow['condition']}, {tomorrow['tmin_c']}–{tomorrow['tmax_c']} °C, rain {tomorrow['rain_mm']} mm ({tomorrow['rain_prob_pct']}% chance)."
        )
    if name == "get_alerts":
        official = result["official_imd_ndma_alerts"]
        derived = result["model_derived_advisories"]
        if not official and not derived:
            return f"No active IMD/NDMA warnings or model-flagged hazards for **{place}** in the next 5 days."
        lines = [f"**{place}**"]
        lines += [f"- ⚠️ {a['severity']}: {a['headline']}" for a in official[:4]]
        lines += [f"- {a['date']}: {a['event']} — {a['detail']}" for a in derived[:4]]
        return "\n".join(lines)
    if name == "get_climate":
        return (
            f"**{place}** ({result['period']}): annual mean temperature trend {result['annual_temp_trend_c_per_decade']} °C per decade, "
            f"rainfall trend {result['annual_rain_trend_mm_per_decade']} mm per decade."
        )
    if name == "get_air_quality":
        return f"**{place}** — India NAQI {result['india_naqi']} ({result['india_naqi_band']}), PM2.5 24 h avg {result['pm2_5_24h_avg']} µg/m³."
    if name == "get_marine":
        if not result.get("available"):
            return result.get("reason", "No marine data.")
        c = result["current"]
        return f"**{place}** — waves {c['wave_height']} m, period {c['wave_period']} s, sea surface {c['sea_surface_temperature']} °C."
    if name == "get_aviation":
        if not result.get("available"):
            return f"No recent METAR for {result['station']}."
        d = result.get("decoded") or {}
        bits = [d.get("wind"), f"visibility {d['visibility']}" if d.get("visibility") else None, ", ".join(d.get("weather") or []) or None,
                "; ".join(d.get("clouds") or []) or None]
        return f"**{result['station']}** {result.get('flight_category') or ''} — " + " · ".join(b for b in bits if b) + f"\n\n`{result['raw_metar']}`"
    if name == "get_farm_advisory":
        w = result["spray"]["windows"]
        irr = result["irrigation"]
        spray = f"Spray window: {w[0]['start'][5:16].replace('T', ' ')} for {w[0]['hours']} h." if w else f"No safe spray window in 48 h (mostly {result['spray']['main_blocker']})."
        return (
            f"**{place}** — {spray}\n\n"
            f"Water balance ({irr['crop'] or 'reference crop'}, 7 d): need {irr['crop_water_need_7d_mm']} mm, effective rain {irr['effective_rain_7d_mm']} mm → {irr['advice']}"
        )
    if name == "get_fishing_advisory":
        return f"**{place}** — **{result['now']}** now ({f"waves {result['wave_now_m']} m, " if result['wave_now_m'] is not None else ""}gusts {result['gust_now_kmh']} km/h). " + " · ".join(
            f"{d['date'][5:]}: {d['verdict']}" for d in result["days"]
        )
    if name == "get_city_advisory":
        peak = result["heat_index_peak"]
        return f"**{place}** — feels-like peak {peak['heat_index']} °C at {peak['time'][11:16]} ({peak['band']}); waterlogging risk {result['waterlogging_risk']}."
    if name == "compare_models":
        return f"Model comparison for **{place}** is shown in the card."
    return json.dumps(result)[:800]


async def run_offline(message: str, ctx: tools.ChatContext, note: bool = True) -> AsyncIterator[dict[str, Any]]:
    icao = re.search(r"\b(V[A-Z]{3})\b", message)
    if icao:
        name, args = "get_aviation", {"icao": icao.group(1)}
    else:
        name = next((tool for tool, pattern in INTENTS if re.search(pattern, message, re.I)), "get_forecast")
        location = _extract_location(message)
        args = {"location": location} if location else {}
        if name == "get_farm_advisory":
            crop = next((c for c in map(advisory.normalize_crop, re.findall(r"\w+", message)) if c), None)
            if crop:
                args["crop"] = crop
    yield _event("status", text=TOOL_STATUS[name], tool=name, args=args)
    result = await _run_tool(name, args, ctx)
    for card in ctx.cards:
        yield _event("card", card=card)
    spoken = _offline_speech(name, result)
    if spoken:
        yield _event("delta", text=f"<speak>{spoken}</speak>")
    yield _event("delta", text=_offline_summary(name, result))
    if note:
        yield _event("delta", text="\n\n_Offline mode: add a `GEMINI_API_KEY` or `GROQ_API_KEY` to `backend/.env` for full conversational answers in every language._")


async def chat(message: str, history: list[dict[str, str]], ctx: tools.ChatContext) -> AsyncIterator[dict[str, Any]]:
    chain = providers.available()
    wait = providers.soonest_free()
    if not chain and wait is not None and wait <= MAX_CAPACITY_WAIT_S:
        yield _event("status", text=f"Waiting {wait:.0f}s for AI capacity", tool="fallback", args={})
        await asyncio.sleep(wait + 0.5)
        chain = providers.available()
    system = system_prompt(ctx)
    failures: list[str] = []
    for index, (provider_cls, model) in enumerate(chain):
        backup_exists = index < len(chain) - 1
        provider = provider_cls(model, system, history, message, retries=[] if backup_exists else [1.5, 3.0])
        emitted = False
        try:
            async for event in run_provider(provider, ctx):
                if not emitted:
                    emitted = True
                    yield _event("provider", name=provider.name, label=provider.label, fallback=index > 0)
                yield event
            providers.succeeded(f"{provider.name}:{model}")
            yield _event("done")
            return
        except Exception as exc:
            failures.append(f"{provider.label}: {exc}")
            providers.bench(f"{provider.name}:{model}", exc)
            log.warning("provider failed: %s: %s", provider.label, str(exc)[:160])
            if emitted:
                yield _event("reset")
            ctx.cards.clear()
            if backup_exists:
                yield _event("status", text=f"{provider.label} busy, switching model", tool="fallback", args={})
    if not chain and providers.chain():
        failures.append("all models cooling down after rate limits")
    try:
        if failures:
            yield _event("provider", name="offline", label="Offline intent mode", fallback=True)
        async for event in run_offline(message, ctx, note=not failures):
            yield event
    except Exception as exc:
        yield _event("error", text=str(exc))
    if failures:
        yield _event("delta", text="\n\n_AI models were unreachable, so this is a data-only answer._")
    yield _event("done")
