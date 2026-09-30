import asyncio
import hashlib
import json
import logging
import math
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import alerts as alert_service
from app.services.cyclones import bearing_word, inside, km
from app.services.http import TTLCache, client, get_retry

log = logging.getLogger("weathergpt.lightning")

HOSTS = ("ws1", "ws7", "ws8", "ws5")
REGION = {"lat": (0.0, 40.0), "lon": (60.0, 100.0)}
KEEP_S = 3 * 3600
UA = "WeatherGPT/0.1 (non-commercial research prototype)"
WORDS = ("lightning", "thunder", "hail", "squall", "dust storm", "duststorm")
NEAR_KM = 10
_polygon_cache = TTLCache(ttl_s=6 * 3600, max_items=2048)
_risk_cache = TTLCache(ttl_s=1200)
_outlook_cache = TTLCache(ttl_s=900)


def lzw_decode(data: str) -> str:
    if not data:
        return ""
    dictionary: dict[int, str] = {}
    current = old = data[0]
    out = [current]
    code = 256
    for ch in data[1:]:
        value = ord(ch)
        phrase = ch if value < 256 else dictionary.get(value, old + current)
        out.append(phrase)
        current = phrase[0]
        dictionary[code] = old + current
        code += 1
        old = phrase
    return "".join(out)


class StrikeFeed:
    def __init__(self) -> None:
        self.strikes: deque[tuple[float, float, float, int]] = deque()
        self.task: asyncio.Task | None = None
        self.connected = False
        self.host: str | None = None
        self.since: float | None = None
        self.last_message: float | None = None
        self.received = 0

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    async def _run(self) -> None:
        import websockets

        backoff = 2.0
        while True:
            for host in HOSTS:
                try:
                    async with websockets.connect(f"wss://{host}.blitzortung.org/", open_timeout=15, ping_interval=30, max_size=2**20, additional_headers={"User-Agent": UA}) as ws:
                        await ws.send(json.dumps({"a": 111}))
                        self.connected, self.host, backoff = True, host, 2.0
                        self.since = self.since or time.time()
                        async for raw in ws:
                            self.add(raw if isinstance(raw, str) else raw.decode("utf-8", "ignore"))
                except asyncio.CancelledError:
                    self.connected = False
                    raise
                except Exception as exc:
                    log.info("lightning feed %s dropped: %s", host, exc)
                self.connected = False
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    def add(self, raw: str) -> None:
        self.last_message = time.time()
        try:
            data = json.loads(lzw_decode(raw))
        except (ValueError, IndexError):
            return
        self.received += 1
        lat, lon = data.get("lat"), data.get("lon")
        if lat is None or lon is None or not (REGION["lat"][0] <= lat <= REGION["lat"][1] and REGION["lon"][0] <= lon <= REGION["lon"][1]):
            return
        self.strikes.append((data.get("time", time.time_ns()) / 1e9, float(lat), float(lon), len(data.get("sig") or [])))
        cutoff = time.time() - KEEP_S
        while self.strikes and self.strikes[0][0] < cutoff:
            self.strikes.popleft()

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "connected": self.connected, "listening_min": round((now - self.since) / 60) if self.since else 0,
            "last_message_s": round(now - self.last_message) if self.last_message else None, "region_strikes": len(self.strikes),
            "source": "Blitzortung.org volunteer detector network (non-commercial use); sparse detector coverage over India, so many strikes are missed",
        }

    def near(self, lat: float, lon: float, radius_km: float, minutes: int) -> list[dict[str, Any]]:
        cutoff = time.time() - minutes * 60
        pad_lat = radius_km / 111
        pad_lon = radius_km / (111 * max(0.2, math.cos(math.radians(lat))))
        out = []
        for t, la, lo, stations in reversed(self.strikes):
            if t < cutoff:
                break
            if abs(la - lat) > pad_lat or abs(lo - lon) > pad_lon:
                continue
            distance = km((lat, lon), (la, lo))
            if distance <= radius_km:
                out.append({"t": round(t, 1), "lat": round(la, 4), "lon": round(lo, 4), "km": round(distance, 1), "stations": stations})
        return out


feed = StrikeFeed()


def motion(strikes: list[dict[str, Any]], place: tuple[float, float]) -> dict[str, Any] | None:
    now = time.time()
    recent = [s for s in strikes if now - s["t"] <= 10 * 60]
    earlier = [s for s in strikes if 20 * 60 <= now - s["t"] <= 30 * 60]
    if len(recent) < 3 or len(earlier) < 3:
        return None
    nearest = min(recent, key=lambda s: s["km"])
    cluster_now = [s for s in recent if km((nearest["lat"], nearest["lon"]), (s["lat"], s["lon"])) <= 40]
    anchor = (sum(s["lat"] for s in cluster_now) / len(cluster_now), sum(s["lon"] for s in cluster_now) / len(cluster_now))
    cluster_then = [s for s in earlier if km(anchor, (s["lat"], s["lon"])) <= 60]
    if len(cluster_then) < 3:
        return None
    then = (sum(s["lat"] for s in cluster_then) / len(cluster_then), sum(s["lon"] for s in cluster_then) / len(cluster_then))
    moved = km(then, anchor)
    speed = moved / (20 / 60)
    before, after = km(place, then), km(place, anchor)
    closing = (before - after) / (20 / 60)
    return {
        "speed_kmh": round(speed), "heading": bearing_word(then, anchor), "closing_kmh": round(closing),
        "eta_min": round(after / closing * 60) if closing > 5 and after > NEAR_KM else None,
        "centre": {"lat": round(anchor[0], 3), "lon": round(anchor[1], 3), "km": round(after, 1)},
    }


def _is_convective(alert: dict[str, Any]) -> bool:
    text = " ".join(str(alert.get(k) or "") for k in ("event", "headline")).lower()
    return any(word in text for word in WORDS)


def _thin(points: list[list[float]], limit: int = 120) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    thinned = points[::step]
    return thinned if thinned[-1] == points[-1] else thinned + [points[-1]]


async def polygons(alert: dict[str, Any]) -> list[list[list[float]]]:
    url = alert.get("polygon_url")
    if not url:
        return []

    async def load() -> list[list[list[float]]]:
        response = await client().get(url, timeout=20)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        rings = []
        for node in root.iter():
            if node.tag.split("}")[-1].lower() != "polygon" or not (node.text or "").strip():
                continue
            ring = []
            for pair in node.text.split():
                try:
                    la, lo = pair.split(",")
                    ring.append([round(float(lo), 3), round(float(la), 3)])
                except ValueError:
                    continue
            if len(ring) >= 3:
                rings.append(_thin(ring))
        return rings

    try:
        return await _polygon_cache.get_or_set(alert["id"], load)
    except Exception as exc:
        log.info("polygon for %s unavailable: %s", alert.get("id"), exc)
        return []


async def official_areas() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    active = []
    for alert in await alert_service.official_alerts():
        if not _is_convective(alert):
            continue
        try:
            if alert.get("expires") and datetime.fromisoformat(alert["expires"]) < now:
                continue
        except ValueError:
            pass
        active.append(alert)
    shapes = await asyncio.gather(*(polygons(a) for a in active))
    return [
        {
            "id": a["id"], "event": a.get("event"), "severity": a.get("severity"), "headline": a.get("headline"), "instruction": a.get("instruction"),
            "issuer": a.get("issuer") or a.get("sender"), "areas": a.get("areas") or [], "effective": a.get("effective"), "expires": a.get("expires"),
            "localized": a.get("localized") or [], "rings": rings,
        }
        for a, rings in zip(active, shapes)
    ]


def covering(areas: list[dict[str, Any]], lat: float, lon: float) -> list[dict[str, Any]]:
    return [a for a in areas if any(inside((lat, lon), ring) for ring in a["rings"])]


async def live(lat: float, lon: float, radius_km: int = 300, minutes: int = 60) -> dict[str, Any]:
    feed.start()
    strikes = feed.near(lat, lon, radius_km, minutes)
    areas = await official_areas()
    here = covering(areas, lat, lon)
    nearest = min(strikes, key=lambda s: s["km"]) if strikes else None
    now = time.time()
    rings = {r: sum(1 for s in strikes if s["km"] <= r and now - s["t"] <= 30 * 60) for r in (10, 20, 30)}
    last_close = max((s["t"] for s in strikes if s["km"] <= NEAR_KM), default=None)
    return {
        "now": datetime.now(timezone.utc).isoformat(), "radius_km": radius_km, "minutes": minutes,
        "strikes": strikes[:4000], "count": len(strikes), "rings_30min": rings,
        "nearest": nearest and {"km": nearest["km"], "direction": bearing_word((lat, lon), (nearest["lat"], nearest["lon"])), "minutes_ago": round((now - nearest["t"]) / 60, 1)},
        "last_within_10km_min": round((now - last_close) / 60, 1) if last_close else None,
        "motion": motion(strikes, (lat, lon)), "feed": feed.status(),
        "official": areas, "official_here": [a["id"] for a in here],
    }


def _thunder_score(code: int | None, cape: float | None, lifted: float | None, prob: float | None) -> int:
    if code in (95, 96, 99):
        return 3 if (cape or 0) >= 1000 or code in (96, 99) else 2
    if (cape or 0) >= 1500 and (lifted if lifted is not None else 0) <= -3 and (prob or 0) >= 40:
        return 2
    if (cape or 0) >= 800 and (lifted if lifted is not None else 0) <= -1 and (prob or 0) >= 25:
        return 1
    return 0


async def risk_grid(lat: float, lon: float, span_deg: float = 3.0, step: float = 0.75, hours: int = 6) -> dict[str, Any]:
    key = f"{round(lat * 2) / 2},{round(lon * 2) / 2}"

    async def load() -> dict[str, Any]:
        centre = (round(lat * 2) / 2, round(lon * 2) / 2)
        n = int(span_deg / step)
        cells = [(round(centre[0] + i * step, 3), round(centre[1] + j * step, 3)) for i in range(-n, n + 1) for j in range(-n, n + 1)]
        results = []
        for start in range(0, len(cells), 50):
            chunk = cells[start:start + 50]
            response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
                "latitude": ",".join(str(c[0]) for c in chunk), "longitude": ",".join(str(c[1]) for c in chunk),
                "hourly": "weather_code,cape,lifted_index,precipitation_probability", "forecast_hours": hours + 1, "timezone": "UTC",
            }, timeout=30)
            data = response.json()
            results.extend(data if isinstance(data, list) else [data])
        grid = []
        for (la, lo), item in zip(cells, results):
            h = item.get("hourly") or {}
            scores = [_thunder_score(c, cp, li, pp) for c, cp, li, pp in zip(h.get("weather_code") or [], h.get("cape") or [], h.get("lifted_index") or [], h.get("precipitation_probability") or [])]
            peak = max(scores, default=0)
            first = next((t for t, s in zip(h.get("time") or [], scores) if s == peak and peak > 0), None)
            grid.append({"lat": la, "lon": lo, "score": peak, "cape": round(max(h.get("cape") or [0])), "time": first and first + "+00:00"})
        return {"step": step, "hours": hours, "cells": grid, "source": "Open-Meteo best-match (ECMWF, GFS, ICON): thunderstorm weather codes, CAPE and lifted index"}

    return await _risk_cache.get_or_set(key, load)


async def outlook(lat: float, lon: float) -> dict[str, Any]:
    key = f"{lat:.2f},{lon:.2f}"

    async def load() -> dict[str, Any]:
        response = await get_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "hourly": "weather_code,cape,lifted_index,precipitation_probability,precipitation,wind_gusts_10m",
            "forecast_hours": 36, "timezone": "UTC",
        }, timeout=25)
        h = response.json()["hourly"]
        hours = []
        for t, code, cape, lifted, prob, rain, gust in zip(h["time"], h["weather_code"], h["cape"], h["lifted_index"], h["precipitation_probability"], h["precipitation"], h["wind_gusts_10m"]):
            hours.append({"time": t + "+00:00", "score": _thunder_score(code, cape, lifted, prob), "code": code, "cape": round(cape or 0), "lifted": lifted, "rain_prob": prob, "rain": rain, "gust": gust})
        risky = [x for x in hours if x["score"] >= 2]
        return {"hours": hours, "next_storm": risky[0]["time"] if risky else None, "peak": max((x["score"] for x in hours), default=0)}

    return await _outlook_cache.get_or_set(key, load)


def _local_headline(alert: dict[str, Any], language: str) -> str | None:
    return next((i["headline"] for i in alert.get("localized") or [] if (i.get("language") or "").lower()[:2] in (language, {"te": "tl"}.get(language, "")) and i.get("headline")), None)


async def notify() -> dict[str, int]:
    from sqlalchemy import select

    from app.db import PhoneSubscriber, Session
    from app.services import phone, smart

    feed.start()
    areas = await official_areas()
    places = await smart._places()
    prefs = await smart._prefs(sorted({c for p in places.values() for c in p["clients"]})) if places else {}
    created = []
    now = time.time()
    for place in places.values():
        hits = covering(areas, place["lat"], place["lon"])
        for alert in hits:
            content = " ".join((alert.get("headline") or "").lower().split())
            for client in place["clients"]:
                language = prefs[client].language if client in prefs else "en"
                title = f"{alert.get('severity') or 'Severe'} · {alert.get('event') or 'Lightning'} — {place['name']}"
                body = _local_headline(alert, language) or alert.get("headline") or ""
                if language != "en" and not _local_headline(alert, language):
                    title, body = await phone.say(title, language), await phone.say(body, language)
                notice = await smart._store(client, "official", alert.get("severity") or "Severe", title, body, place,
                                            {"alert_id": alert["id"], "event": alert.get("event"), "issuer": alert.get("issuer"), "expires": alert.get("expires"), "polygon": True},
                                            f"official:{hashlib.sha1(content.encode()).hexdigest()[:24]}")
                if notice:
                    created.append(notice)
        close = [s for s in feed.near(place["lat"], place["lon"], NEAR_KM, 10)]
        if close:
            nearest = min(close, key=lambda s: s["km"])
            hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
            title_en = f"Lightning {nearest['km']:.0f} km from {place['name']}"
            body_en = f"{len(close)} lightning strikes within {NEAR_KM} km in the last 10 minutes, the nearest {nearest['km']:.0f} km {bearing_word((place['lat'], place['lon']), (nearest['lat'], nearest['lon']))}. Go indoors now and stay in for 30 minutes after the last thunder."
            for client in place["clients"]:
                pref = prefs.get(client)
                if pref and pref.kinds and "lightning" not in pref.kinds and "storm" not in pref.kinds:
                    continue
                language = pref.language if pref else "en"
                title, body = (title_en, body_en) if language == "en" else (await phone.say(title_en, language), await phone.say(body_en, language))
                notice = await smart._store(client, "lightning", "Severe", title, body, place, {"strikes": len(close), "nearest_km": nearest["km"], "detected_at": now}, f"lightning:{round(place['lat'], 2)},{round(place['lon'], 2)}:{hour}")
                if notice:
                    created.append(notice)
    delivered = await smart.deliver(created)
    async with Session() as s:
        subs = (await s.scalars(select(PhoneSubscriber).where(PhoneSubscriber.active.is_(True), PhoneSubscriber.confirmed.is_(True), PhoneSubscriber.lat.is_not(None)))).all()
    sms = 0
    for sub in subs:
        for alert in covering(areas, sub.lat, sub.lon):
            text = _local_headline(alert, sub.language) or await phone.say(f"WeatherGPT: {alert.get('event') or 'Lightning'} warning for {sub.place_name or 'your area'} until {alert.get('expires', '')[11:16]}. {alert.get('headline') or ''}", sub.language)
            if sub.sms and await phone.send_sms(sub.phone, text, kind="warning", dedup=f"lightning-alert:{alert['id']}", max_segments=3):
                sms += 1
    return {"notices": delivered["created"], "pushed": delivered["pushed"], "sms": sms}


async def status_for_agent(lat: float, lon: float, name: str) -> dict[str, Any]:
    data, look = await asyncio.gather(live(lat, lon, 150, 60), outlook(lat, lon))
    here = [a for a in data["official"] if a["id"] in data["official_here"]]
    return {
        "place": name,
        "official_warning_covering_place": [{"event": a["event"], "severity": a["severity"], "headline": a["headline"], "issuer": a["issuer"], "until": a["expires"]} for a in here],
        "official_convective_warnings_active_in_india": len(data["official"]),
        "live_strikes_within_150km_last_hour": data["count"], "strikes_last_30min": data["rings_30min"], "nearest_strike": data["nearest"], "storm_motion": data["motion"],
        "detector_note": data["feed"]["source"],
        "model_thunder_outlook_next_36h": {"next_likely_storm_utc": look["next_storm"], "peak_score_0_to_3": look["peak"], "hours_with_score_2_or_more": [h["time"] for h in look["hours"] if h["score"] >= 2][:12]},
        "safety": "30/30 rule: go indoors if thunder follows lightning within 30 seconds, stay in until 30 minutes after the last thunder. Avoid trees, open fields, water, towers and metal; crouch low on the balls of your feet if caught outside.",
    }
