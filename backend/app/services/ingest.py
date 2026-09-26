import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
from app.db import Alert, Delivery, IngestRun, Observation, Session, Subscription, backend_name, utcnow
from app.services import alerts as alert_service
from app.services import weather
from app.services.http import get_retry
from app.services.realtime import hub

log = logging.getLogger("weathergpt.ingest")

INDIA_BBOX = "6,68,37.5,98"
_tasks: list[asyncio.Task] = []


def _insert(model):
    return pg_insert(model) if backend_name() == "postgresql" else sqlite_insert(model)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    parsed = parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return parsed.replace(tzinfo=None) if backend_name() == "sqlite" else parsed


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()


def alert_payload(row: Alert) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source,
        "issuer": row.issuer,
        "sender": row.sender,
        "event": row.event,
        "severity": row.severity,
        "urgency": row.urgency,
        "certainty": row.certainty,
        "headline": row.headline,
        "instruction": row.instruction,
        "areas": row.areas,
        "localized": row.localized,
        "link": row.link,
        "sent": iso(row.sent),
        "effective": iso(row.effective),
        "expires": iso(row.expires),
    }


def _place(sub: Subscription) -> dict[str, Any]:
    return {"name": sub.name, "district": sub.district, "state": sub.state, "lat": sub.lat, "lon": sub.lon}


async def _record(job: str, runner: Callable[[], Awaitable[tuple[int, int, str | None]]]) -> None:
    async with Session() as s:
        run = IngestRun(job=job)
        s.add(run)
        await s.commit()
        try:
            items, new_items, detail = await runner()
            run.ok, run.items, run.new_items, run.detail = True, items, new_items, detail
        except Exception as exc:
            log.warning("ingest job %s failed: %s", job, exc)
            run.ok, run.detail = False, f"{type(exc).__name__}: {exc}"[:500]
        run.finished_at = utcnow()
        s.add(run)
        await s.commit()


async def notify_client(client_id: str, alerts: list[dict[str, Any]] | None = None) -> int:
    async with Session() as s:
        subs = (await s.scalars(select(Subscription).where(Subscription.client_id == client_id))).all()
        if not subs:
            return 0
        now = utcnow()
        rows = (await s.scalars(select(Alert).where((Alert.expires.is_(None)) | (Alert.expires >= now)))).all()
        candidates = [alert_payload(r) for r in rows] if alerts is None else alerts
        already = set((await s.scalars(select(Delivery.alert_id).where(Delivery.client_id == client_id))).all())
        sent = 0
        for sub in subs:
            for alert in alert_service.alerts_for_place([a for a in candidates if a["id"] not in already], _place(sub)):
                already.add(alert["id"])
                delivery = Delivery(alert_id=alert["id"], client_id=client_id, place_name=sub.name, match=alert["match"])
                s.add(delivery)
                if await hub.send(client_id, {"type": "alert", "place": _place(sub), "match": alert["match"], "alert": alert}):
                    delivery.delivered_at = utcnow()
                    sent += 1
        await s.commit()
        return sent


async def ingest_alerts() -> tuple[int, int, str | None]:
    feed = await alert_service.official_alerts(fresh=True)
    now = utcnow()
    new_alerts: list[dict[str, Any]] = []
    async with Session() as s:
        known = set((await s.scalars(select(Alert.id).where(Alert.id.in_([a["id"] for a in feed])))).all()) if feed else set()
        for a in feed:
            values = {
                "source": a["source"], "issuer": a.get("issuer"), "sender": a.get("sender"), "event": a.get("event"),
                "severity": a.get("severity") or "Unknown", "urgency": a.get("urgency"), "certainty": a.get("certainty"),
                "headline": a.get("headline") or "", "instruction": a.get("instruction"), "areas": a.get("areas") or [],
                "localized": a.get("localized") or [], "link": a.get("link"), "sent": _parse(a.get("sent")),
                "effective": _parse(a.get("effective")), "expires": _parse(a.get("expires")), "last_seen_at": now,
            }
            if a["id"] in known:
                existing = await s.get(Alert, a["id"])
                existing.last_seen_at = now
                existing.expires = values["expires"]
            else:
                s.add(Alert(id=a["id"], first_seen_at=now, **values))
                new_alerts.append(a)
        await s.commit()
        clients = (await s.scalars(select(Subscription.client_id).distinct())).all()
    pushed = 0
    if new_alerts:
        for client_id in clients:
            pushed += await notify_client(client_id, new_alerts)
    return len(feed), len(new_alerts), f"pushed {pushed} notifications to {len(clients)} subscribed clients"


async def ingest_observations() -> tuple[int, int, str | None]:
    response = await get_retry(weather.METAR_URL, params={"bbox": INDIA_BBOX, "format": "json"}, timeout=60)
    response.raise_for_status()
    rows = [r for r in (response.json() if response.content.strip() else []) if r.get("lat") is not None and (r.get("reportTime") or r.get("obsTime"))]
    new = 0
    async with Session() as s:
        for r in rows:
            observed = _parse(r.get("reportTime")) or (_parse(datetime.fromtimestamp(r["obsTime"], timezone.utc).isoformat()) if isinstance(r.get("obsTime"), (int, float)) else None)
            if observed is None:
                continue
            statement = _insert(Observation).values(
                station=r.get("icaoId"), name=r.get("name"), lat=r["lat"], lon=r["lon"], observed_at=observed,
                temp_c=r.get("temp"), dewpoint_c=r.get("dewp"),
                wind_kmh=round(r["wspd"] * 1.852, 1) if isinstance(r.get("wspd"), (int, float)) else None,
                wind_dir=str(r.get("wdir")) if r.get("wdir") is not None else None,
                gust_kmh=round(r["wgst"] * 1.852, 1) if isinstance(r.get("wgst"), (int, float)) else None,
                visibility=str(r.get("visib")) if r.get("visib") is not None else None,
                pressure_hpa=r.get("altim"), weather=r.get("wxString"), raw=r.get("rawOb"),
            ).on_conflict_do_nothing(index_elements=["station", "observed_at"])
            result = await s.execute(statement)
            new += result.rowcount or 0
        cutoff = utcnow() - timedelta(days=30)
        await s.execute(delete(Observation).where(Observation.observed_at < cutoff))
        await s.commit()
    return len(rows), new, f"{len({r.get('icaoId') for r in rows})} stations across India"


async def warm_forecasts() -> tuple[int, int, str | None]:
    async with Session() as s:
        coords = (await s.execute(select(Subscription.lat, Subscription.lon).distinct())).all()
    done = 0
    for lat, lon in coords:
        try:
            await asyncio.gather(weather.forecast(lat, lon), weather.air_quality(lat, lon))
            done += 1
        except Exception as exc:
            log.info("warm failed for %s,%s: %s", lat, lon, exc)
        await asyncio.sleep(0.3)
    return len(coords), done, None


JOBS: dict[str, tuple[Callable[[], Awaitable[tuple[int, int, str | None]]], Callable[[], int]]] = {
    "alerts": (ingest_alerts, lambda: get_settings().alert_poll_s),
    "observations": (ingest_observations, lambda: get_settings().observation_poll_s),
    "warm": (warm_forecasts, lambda: get_settings().warm_poll_s),
}


async def _loop(name: str) -> None:
    runner, interval = JOBS[name]
    await asyncio.sleep(random.uniform(1, 5))
    while True:
        await _record(name, runner)
        await asyncio.sleep(interval() * random.uniform(0.9, 1.1))


def start() -> None:
    if not get_settings().workers_enabled or _tasks:
        return
    for name in JOBS:
        _tasks.append(asyncio.create_task(_loop(name), name=f"ingest-{name}"))


async def stop() -> None:
    for task in _tasks:
        task.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()


async def status() -> dict[str, Any]:
    async with Session() as s:
        jobs = {}
        for name in JOBS:
            last = (await s.scalars(select(IngestRun).where(IngestRun.job == name).order_by(IngestRun.started_at.desc()).limit(1))).first()
            last_ok = (await s.scalars(select(IngestRun).where(IngestRun.job == name, IngestRun.ok.is_(True)).order_by(IngestRun.started_at.desc()).limit(1))).first()
            jobs[name] = {
                "interval_s": JOBS[name][1](),
                "last_run": iso(last.started_at) if last else None,
                "last_ok": last.ok if last else None,
                "last_detail": last.detail if last else None,
                "last_success": iso(last_ok.finished_at) if last_ok else None,
                "items": last.items if last else 0,
                "new_items": last.new_items if last else 0,
            }
        counts = {
            "alerts_stored": await s.scalar(select(func.count()).select_from(Alert)),
            "alerts_active": await s.scalar(select(func.count()).select_from(Alert).where((Alert.expires.is_(None)) | (Alert.expires >= utcnow()))),
            "observations_stored": await s.scalar(select(func.count()).select_from(Observation)),
            "subscriptions": await s.scalar(select(func.count()).select_from(Subscription)),
            "deliveries": await s.scalar(select(func.count()).select_from(Delivery)),
        }
    return {"database": backend_name(), "workers": bool(_tasks), "jobs": jobs, "counts": counts, "realtime": hub.stats()}
