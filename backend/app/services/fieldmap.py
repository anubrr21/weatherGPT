import asyncio
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services import alerts as alert_service
from app.services.http import TTLCache, get_retry
from app.services.lightning import polygons

BOX = {"south": 5.0, "north": 38.0, "west": 66.5, "east": 99.5}
STEP = 1.5
HOURS = 48
EVERY = 3
CHUNK = 120
VARIABLES = "temperature_2m,wind_speed_10m,wind_direction_10m,precipitation,cloud_cover,pressure_msl"
_field_cache = TTLCache(ttl_s=3 * 3600)
_warning_cache = TTLCache(ttl_s=300)


def grid() -> tuple[list[float], list[float]]:
    lats = [round(BOX["south"] + i * STEP, 2) for i in range(int((BOX["north"] - BOX["south"]) / STEP) + 1)]
    lons = [round(BOX["west"] + j * STEP, 2) for j in range(int((BOX["east"] - BOX["west"]) / STEP) + 1)]
    return lats, lons


def components(speed: float | None, direction: float | None) -> tuple[float, float]:
    if speed is None or direction is None:
        return 0.0, 0.0
    radians = math.radians(direction)
    return round(-speed * math.sin(radians), 1), round(-speed * math.cos(radians), 1)


async def fields() -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        lats, lons = grid()
        cells = [(la, lo) for la in lats for lo in lons]
        chunks = [cells[i:i + CHUNK] for i in range(0, len(cells), CHUNK)]

        async def fetch(chunk: list[tuple[float, float]]) -> list[dict[str, Any]]:
            response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
                "latitude": ",".join(str(c[0]) for c in chunk), "longitude": ",".join(str(c[1]) for c in chunk),
                "hourly": VARIABLES, "forecast_hours": HOURS, "timezone": "UTC", "wind_speed_unit": "kmh",
            }, timeout=60)
            data = response.json()
            return data if isinstance(data, list) else [data]

        results: list[dict[str, Any]] = []
        for part in await asyncio.gather(*(fetch(c) for c in chunks)):
            results.extend(part)
        times = [t + ":00+00:00" if len(t) == 16 else t for t in results[0]["hourly"]["time"]][::EVERY]
        frames = len(times)
        out = {k: [[0.0] * len(cells) for _ in range(frames)] for k in ("temp", "u", "v", "speed", "rain", "cloud", "pressure")}
        for c, item in enumerate(results):
            h = item["hourly"]
            for f in range(frames):
                i = f * EVERY
                window = slice(i, min(i + EVERY, len(h["time"])))
                u, v = components(h["wind_speed_10m"][i], h["wind_direction_10m"][i])
                out["temp"][f][c] = round(h["temperature_2m"][i] if h["temperature_2m"][i] is not None else 0.0, 1)
                out["u"][f][c], out["v"][f][c] = u, v
                out["speed"][f][c] = round(h["wind_speed_10m"][i] or 0.0, 1)
                out["rain"][f][c] = round(sum(x or 0.0 for x in h["precipitation"][window]), 1)
                out["cloud"][f][c] = round(h["cloud_cover"][i] or 0.0)
                out["pressure"][f][c] = round(h["pressure_msl"][i] or 0.0, 1)
        return {
            "generated": datetime.now(timezone.utc).isoformat(), "lats": lats, "lons": lons, "step": STEP, "times": times, "hours_per_frame": EVERY,
            "fields": out, "source": f"Open-Meteo best-match forecast on a {STEP}° grid ({len(cells)} points), next {HOURS} hours",
        }

    return await _field_cache.get_or_set("india", load)


async def warnings() -> dict[str, Any]:
    async def load() -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        active = []
        for alert in await alert_service.official_alerts():
            try:
                if alert.get("expires") and datetime.fromisoformat(alert["expires"]) < now:
                    continue
            except ValueError:
                pass
            active.append(alert)
        shapes = await asyncio.gather(*(polygons(a) for a in active))
        items = [
            {
                "id": a["id"], "event": a.get("event") or "Warning", "severity": a.get("severity"), "headline": a.get("headline"),
                "issuer": a.get("issuer") or a.get("sender"), "areas": a.get("areas") or [], "expires": a.get("expires"), "rings": rings,
            }
            for a, rings in zip(active, shapes)
        ]
        return {
            "fetched": now.isoformat(), "count": len(items), "mapped": sum(1 for i in items if i["rings"]),
            "by_event": Counter(i["event"] for i in items).most_common(), "by_severity": Counter(i["severity"] for i in items).most_common(), "warnings": items,
        }

    return await _warning_cache.get_or_set("india", load)
