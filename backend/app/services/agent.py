import asyncio
import json
import re
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

from app.config import get_settings
from app.services import tools
from app.services.http import client

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
MAX_TOOL_ROUNDS = 5

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
}


def system_prompt(ctx: tools.ChatContext) -> str:
    language = LANGUAGES.get(ctx.language, "English")
    where = (
        f"The user's device is at lat {ctx.lat:.4f}, lon {ctx.lon:.4f}" + (f" ({ctx.place_name})" if ctx.place_name else "")
        if ctx.lat is not None and ctx.lon is not None
        else "The user's device location is unknown"
    )
    return f"""You are WeatherGPT, a meteorological assistant for India built on live data: NWP models (GFS, ECMWF, ICON), official IMD/NDMA CAP warnings, ERA5 climate reanalysis, CPCB-style AQI, marine and METAR data.

Current local date-time: {datetime.now().strftime('%A %d %B %Y, %H:%M')}. {where}.

Rules:
- Always call tools for real data. Never invent numbers. If a tool fails, say so plainly.
- Reply in {language} unless the user clearly writes in another language; then reply in that language. Use the native script. Keep place names recognisable.
- Be concise and actionable: lead with the direct answer, then key numbers, then practical advice. Short paragraphs or tight bullet points; no tables (the app renders rich cards from tool data next to your reply).
- Tailor advice to the user's role when evident: farmers (sowing, spraying, irrigation, harvest windows, using rain and evapotranspiration), fishermen/marine (wave height, go/no-go), aviation (flight category, winds, visibility), urban (commute, waterlogging, heat), disaster managers (severity, timing, affected areas).
- For safety questions, prioritise official IMD/NDMA warnings and clearly distinguish them from model-derived advisories. Include specific protective actions.
- Express uncertainty honestly: forecasts beyond 3 days are less reliable; mention model disagreement when relevant.
- Temperatures in °C, rain in mm, wind in km/h (knots for aviation)."""


def _history_to_contents(history: list[dict[str, str]], message: str) -> list[dict[str, Any]]:
    contents = []
    for turn in history[-12:]:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        contents.append({"role": "model" if turn.get("role") == "assistant" else "user", "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


async def _stream_gemini(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    settings = get_settings()
    url = GEMINI_URL.format(model=settings.gemini_model)
    delays = [1.5, 3.0, 6.0]
    for attempt in range(len(delays) + 1):
        async with client().stream(
            "POST",
            url,
            params={"alt": "sse"},
            headers={"x-goog-api-key": settings.gemini_api_key},
            json=payload,
            timeout=httpx.Timeout(90, connect=15),
        ) as response:
            if response.status_code in (429, 500, 503) and attempt < len(delays):
                await response.aread()
                await asyncio.sleep(delays[attempt])
                continue
            if response.status_code >= 400:
                body = (await response.aread()).decode(errors="ignore")
                raise RuntimeError(f"Gemini error {response.status_code}: {body[:300]}")
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        yield json.loads(chunk)
            return


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


async def run_llm(message: str, history: list[dict[str, str]], ctx: tools.ChatContext) -> AsyncIterator[dict[str, Any]]:
    contents = _history_to_contents(history, message)
    base = {
        "systemInstruction": {"parts": [{"text": system_prompt(ctx)}]},
        "tools": [{"functionDeclarations": tools.TOOL_DECLARATIONS}],
        "generationConfig": {"temperature": 0.4},
    }
    for _ in range(MAX_TOOL_ROUNDS):
        model_parts: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []
        async for chunk in _stream_gemini({**base, "contents": contents}):
            for candidate in chunk.get("candidates", [])[:1]:
                for part in candidate.get("content", {}).get("parts", []):
                    model_parts.append(part)
                    if "functionCall" in part:
                        calls.append(part["functionCall"])
                    elif part.get("text") and not part.get("thought"):
                        yield _event("delta", text=part["text"])
        contents.append({"role": "model", "parts": model_parts or [{"text": ""}]})
        if not calls:
            return
        for call in calls:
            yield _event("status", text=TOOL_STATUS.get(call["name"], call["name"]), tool=call["name"], args=call.get("args", {}))
        before = len(ctx.cards)
        results = await asyncio.gather(*(_run_tool(c["name"], c.get("args") or {}, ctx) for c in calls))
        for card in ctx.cards[before:]:
            yield _event("card", card=card)
        contents.append({
            "role": "user",
            "parts": [{"functionResponse": {"name": c["name"], "response": r}} for c, r in zip(calls, results)],
        })
    yield _event("delta", text="\n\n(Stopped after too many data lookups.)")


INTENTS = [
    ("get_alerts", r"alert|warn|cyclone|flood|storm|safe|danger|चेतावनी|तूफान|बाढ़|హెచ్చరిక|எச்சரிக்கை|সতর্ক"),
    ("get_climate", r"climate|trend|histor|normal|hotter|warmer|\d+ years|past years|last year|जलवायु|ఇతిహాస|காலநிலை"),
    ("compare_models", r"model|gfs|ecmwf|icon|confiden|uncertain"),
    ("get_air_quality", r"aqi|air quality|pollution|pm2|smog|प्रदूषण"),
    ("get_marine", r"sea|wave|marine|fish|boat|tide|समुद्र|मछु"),
]


def _extract_location(message: str) -> str | None:
    match = re.search(r"\b(?:in|at|for|near|of)\s+([A-Za-z][A-Za-z .'-]{2,40}?)(?:\s+(?:today|tomorrow|now|this|next|tonight|on|during|weather)\b|[?.!,]|$)", message, re.I)
    if match:
        candidate = match.group(1).strip()
        if candidate.lower() not in {"the", "my area", "here", "my location", "today", "tomorrow"}:
            return candidate
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
        return f"**{result['station']}** {result.get('flight_category') or ''} — `{result['raw_metar']}`"
    if name == "compare_models":
        return f"Model comparison for **{place}** is shown in the card."
    return json.dumps(result)[:800]


async def run_offline(message: str, ctx: tools.ChatContext) -> AsyncIterator[dict[str, Any]]:
    icao = re.search(r"\b(V[A-Z]{3})\b", message)
    if icao:
        name, args = "get_aviation", {"icao": icao.group(1)}
    else:
        name = next((tool for tool, pattern in INTENTS if re.search(pattern, message, re.I)), "get_forecast")
        location = _extract_location(message)
        args = {"location": location} if location else {}
    yield _event("status", text=TOOL_STATUS[name], tool=name, args=args)
    result = await _run_tool(name, args, ctx)
    for card in ctx.cards:
        yield _event("card", card=card)
    yield _event("delta", text=_offline_summary(name, result))
    yield _event("delta", text="\n\n_Offline mode: add a `GEMINI_API_KEY` to `backend/.env` for full conversational answers in every language._")


async def chat(message: str, history: list[dict[str, str]], ctx: tools.ChatContext) -> AsyncIterator[dict[str, Any]]:
    try:
        if get_settings().llm_enabled:
            async for event in run_llm(message, history, ctx):
                yield event
        else:
            async for event in run_offline(message, ctx):
                yield event
    except Exception as exc:
        yield _event("error", text=str(exc))
    yield _event("done")
