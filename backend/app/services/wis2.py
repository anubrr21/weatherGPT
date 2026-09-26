import asyncio
import json
import logging
import ssl
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import paho.mqtt.client as mqtt
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import get_settings
from app.db import Observation, Session, Wis2Message, backend_name
from app.services import bufr_obs, synop
from app.services.http import client

log = logging.getLogger("weathergpt.wis2")

TEXT_SYNOP = ("SM", "SI", "SN")


def _insert(model):
    return pg_insert(model) if backend_name() == "postgresql" else sqlite_insert(model)


def _db_time(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None) if backend_name() == "sqlite" else value


def parse_topic(topic: str) -> dict[str, Any]:
    parts = topic.split("/")
    info: dict[str, Any] = {"centre": parts[3] if len(parts) > 3 else None, "policy": None, "gts": None, "india": False}
    if "data" in parts:
        rest = parts[parts.index("data") + 1:]
        info["policy"] = rest[0] if rest else None
        if len(rest) >= 7 and all(len(x) == 1 for x in rest[1:5]):
            t1, t2, a1, a2, ii, cccc = rest[1], rest[2], rest[3], rest[4], rest[5], rest[6]
            info["gts"] = {"ttaaii": f"{t1}{t2}{a1}{a2}{ii}", "cccc": cccc, "t1t2": t1 + t2, "area": a1 + a2}
            info["india"] = a1 + a2 == "IN"
    if (info["centre"] or "").startswith("in-"):
        info["india"] = True
    return info


class Wis2Subscriber:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self.client: mqtt.Client | None = None
        self.consumer: asyncio.Task | None = None
        self.connected = False
        self.started_at: float | None = None
        self.last_error: str | None = None
        self.total = 0
        self.centres: Counter = Counter()
        self.recent = deque(maxlen=3000)
        self.india_recent: deque = deque(maxlen=25)
        self.bulletins_decoded = 0
        self.observations_added = 0
        self._processed: set[str] = set()
        self.bufr_decoded = 0
        self.bufr_failed = 0
        self._downloads = asyncio.Semaphore(6)
        self._lock = threading.Lock()

    def _on_connect(self, cl, userdata, flags, reason, properties=None):
        self.connected = not reason.is_failure
        if self.connected:
            cl.subscribe(get_settings().wis2_topic, qos=0)
            log.info("wis2 connected to %s", get_settings().wis2_broker)
        else:
            self.last_error = f"connect refused: {reason}"

    def _on_disconnect(self, cl, userdata, flags, reason, properties=None):
        self.connected = False
        if reason.is_failure:
            self.last_error = f"disconnected: {reason}"

    def _on_message(self, cl, userdata, msg):
        if self.loop and self.queue:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (msg.topic, msg.payload, time.time()))

    def start(self) -> None:
        settings = get_settings()
        if not settings.wis2_enabled or self.client:
            return
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=20000)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"weathergpt-{int(time.time())}", clean_session=True)
        self.client.username_pw_set(settings.wis2_username, settings.wis2_password)
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.reconnect_delay_set(min_delay=2, max_delay=120)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.started_at = time.time()
        try:
            self.client.connect_async(settings.wis2_broker, 8883, keepalive=60)
            self.client.loop_start()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("wis2 start failed: %s", exc)
        self.consumer = asyncio.create_task(self._consume(), name="wis2-consumer")
        self.backfill = asyncio.create_task(self._backfill(), name="wis2-backfill")

    async def stop(self) -> None:
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
        if getattr(self, "backfill", None):
            self.backfill.cancel()
        if self.consumer:
            self.consumer.cancel()
            await asyncio.gather(self.consumer, return_exceptions=True)
            self.consumer = None

    async def _consume(self) -> None:
        assert self.queue
        while True:
            topic, payload, received = await self.queue.get()
            try:
                await self._handle(topic, payload, received)
            except Exception as exc:
                log.info("wis2 message failed: %s", exc)

    async def _handle(self, topic: str, payload: bytes, received: float) -> None:
        info = parse_topic(topic)
        self.total += 1
        self.centres[info["centre"]] += 1
        self.recent.append(received)
        if not info["india"]:
            return
        try:
            body = json.loads(payload)
        except ValueError:
            return
        props = body.get("properties", {})
        data_id = props.get("data_id") or topic
        link = next((l.get("href") for l in body.get("links", []) if l.get("rel") in ("canonical", "item")), None)
        gts = info["gts"] or {}
        bulletin = data_id.split("/")[-1].split("_")[0] if gts else None
        self.india_recent.appendleft({"topic": topic, "bulletin": bulletin, "href": link, "pubtime": props.get("pubtime"), "received": received})
        async with Session() as s:
            await s.execute(
                _insert(Wis2Message)
                .values(
                    data_id=data_id[:255], topic=topic[:255], centre=info["centre"], policy=info["policy"],
                    bulletin=bulletin, href=link, pubtime=props.get("pubtime"),
                    received_at=_db_time(datetime.fromtimestamp(received, timezone.utc)),
                )
                .on_conflict_do_nothing(index_elements=["data_id"])
            )
            await s.commit()
        if gts.get("t1t2") in TEXT_SYNOP and link and info["policy"] == "core" and bulletin and bulletin not in self._processed:
            self._processed.add(bulletin)
            await self._decode(link, bulletin)
        elif info["centre"] == "in-imd" and link and link.endswith((".bufr4", ".bufr")) and "synop" in topic:
            asyncio.create_task(self._decode_bufr(link))

    async def _backfill(self, hours: int = 6) -> None:
        await asyncio.sleep(3)
        since = _db_time(datetime.now(timezone.utc) - timedelta(hours=hours))
        async with Session() as s:
            links = (await s.scalars(
                select(Wis2Message.href).where(Wis2Message.centre == "in-imd", Wis2Message.received_at >= since, Wis2Message.href.is_not(None))
            )).all()
        await asyncio.gather(*(self._decode_bufr(link) for link in links if link.endswith((".bufr4", ".bufr"))))
        log.info("wis2 backfill checked %d IMD messages", len(links))

    async def _decode_bufr(self, link: str) -> None:
        async with self._downloads:
            try:
                response = await client().get(link, timeout=30)
                response.raise_for_status()
                obs = bufr_obs.decode_observation(response.content)
            except Exception as exc:
                self.bufr_failed += 1
                log.info("imd bufr decode failed for %s: %s", link, exc)
                return
        if not obs or obs.get("temp_c") is None:
            return
        self.bufr_decoded += 1
        self.observations_added += await self._store([obs], "IMD WIS2")

    async def _store(self, reports: list[dict[str, Any]], label: str) -> int:
        added = 0
        async with Session() as s:
            for o in reports:
                wind_dir = o.get("wind_dir_deg")
                result = await s.execute(
                    _insert(Observation)
                    .values(
                        station=o["station"], name=f"{o.get('name') or o['station']} ({label})", lat=o["lat"], lon=o["lon"],
                        observed_at=_db_time(o["observed_at"]), temp_c=o.get("temp_c"), dewpoint_c=o.get("dewpoint_c"),
                        wind_kmh=o.get("wind_kmh"), wind_dir=str(wind_dir) if wind_dir is not None else None,
                        visibility=f"{o['visibility_km']} km" if o.get("visibility_km") is not None else None,
                        pressure_hpa=o.get("pressure_hpa"), weather=o.get("weather"), raw=(o.get("raw") or "")[:500] or None,
                    )
                    .on_conflict_do_nothing(index_elements=["station", "observed_at"])
                )
                added += result.rowcount or 0
            await s.commit()
        return added

    async def _decode(self, link: str, bulletin: str) -> None:
        response = await client().get(link, timeout=30)
        if response.status_code != 200:
            return
        text = response.content.decode("latin-1", errors="ignore")
        reports = [o for o in synop.decode_bulletin(text) if o.get("lat") is not None and o.get("temp_c") is not None]
        self.bulletins_decoded += 1
        if not reports:
            return
        added = await self._store(reports, "IMD SYNOP")
        self.observations_added += added
        log.info("wis2 decoded %s: %d reports, %d new observations", bulletin, len(reports), added)

    async def status(self) -> dict[str, Any]:
        now = time.time()
        per_minute = sum(1 for t in self.recent if now - t <= 60)
        async with Session() as s:
            india_total = await s.scalar(select(func.count()).select_from(Wis2Message))
            synop_obs = await s.scalar(select(func.count()).select_from(Observation).where(Observation.name.like("%(IMD SYNOP)")))
            imd_obs = await s.scalar(select(func.count()).select_from(Observation).where(Observation.name.like("%(IMD WIS2)")))
            imd_stations = await s.scalar(select(func.count(func.distinct(Observation.station))).where(Observation.name.like("%(IMD WIS2)")))
        return {
            "enabled": get_settings().wis2_enabled,
            "broker": get_settings().wis2_broker,
            "connected": self.connected,
            "uptime_s": round(now - self.started_at) if self.started_at else None,
            "last_error": self.last_error,
            "messages_total": self.total,
            "messages_per_minute": per_minute,
            "centres": self.centres.most_common(12),
            "india_messages_stored": india_total,
            "india_recent": list(self.india_recent)[:10],
            "synop_bulletins_decoded": self.bulletins_decoded,
            "synop_observations_stored": synop_obs,
            "imd_bufr_decoded": self.bufr_decoded,
            "imd_bufr_failed": self.bufr_failed,
            "imd_observations_stored": imd_obs,
            "imd_stations": imd_stations,
            "station_catalogue": len(synop.stations()),
        }


subscriber = Wis2Subscriber()
