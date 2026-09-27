from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def utcnow() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(tzinfo=None) if get_settings().database_url.strip() == "" else now


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    issuer: Mapped[str | None] = mapped_column(String(160))
    sender: Mapped[str | None] = mapped_column(String(160))
    event: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    urgency: Mapped[str | None] = mapped_column(String(40))
    certainty: Mapped[str | None] = mapped_column(String(40))
    headline: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str | None] = mapped_column(Text)
    areas: Mapped[list[Any]] = mapped_column(JSON, default=list)
    localized: Mapped[list[Any]] = mapped_column(JSON, default=list)
    link: Mapped[str | None] = mapped_column(Text)
    sent: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    effective: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("client_id", "lat", "lon", name="uq_subscription_place"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(160))
    district: Mapped[str | None] = mapped_column(String(160))
    state: Mapped[str | None] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("alert_id", "client_id", name="uq_delivery"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    place_name: Mapped[str] = mapped_column(String(160))
    match: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("station", "observed_at", name="uq_observation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station: Mapped[str] = mapped_column(String(8), index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    temp_c: Mapped[float | None] = mapped_column(Float)
    dewpoint_c: Mapped[float | None] = mapped_column(Float)
    wind_kmh: Mapped[float | None] = mapped_column(Float)
    wind_dir: Mapped[str | None] = mapped_column(String(8))
    gust_kmh: Mapped[float | None] = mapped_column(Float)
    visibility: Mapped[str | None] = mapped_column(String(16))
    pressure_hpa: Mapped[float | None] = mapped_column(Float)
    weather: Mapped[str | None] = mapped_column(String(80))
    raw: Mapped[str | None] = mapped_column(Text)


class Wis2Message(Base):
    __tablename__ = "wis2_messages"

    data_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    topic: Mapped[str] = mapped_column(String(255))
    centre: Mapped[str | None] = mapped_column(String(80), index=True)
    policy: Mapped[str | None] = mapped_column(String(20))
    bulletin: Mapped[str | None] = mapped_column(String(40), index=True)
    href: Mapped[str | None] = mapped_column(Text)
    pubtime: Mapped[str | None] = mapped_column(String(40))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(default=False)
    items: Mapped[int] = mapped_column(Integer, default=0)
    new_items: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text)


class Device(Base):
    __tablename__ = "devices"

    token: Mapped[str] = mapped_column(String(512), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class NotifyPrefs(Base):
    __tablename__ = "notify_prefs"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    role: Mapped[str] = mapped_column(String(32), default="general")
    crops: Mapped[list[Any]] = mapped_column(JSON, default=list)
    briefing_at: Mapped[str | None] = mapped_column(String(5), default="06:30")
    quiet_from: Mapped[str | None] = mapped_column(String(5), default="22:00")
    quiet_to: Mapped[str | None] = mapped_column(String(5), default="06:00")
    kinds: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notice(Base):
    __tablename__ = "notices"
    __table_args__ = (UniqueConstraint("client_id", "dedup_key", name="uq_notice"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="Info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    place_name: Mapped[str] = mapped_column(String(160))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed: Mapped[bool] = mapped_column(default=False)
    streamed: Mapped[bool] = mapped_column(default=False)


def database_url() -> str:
    url = get_settings().database_url.strip()
    if url:
        return url
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{(DATA_DIR / 'weathergpt.db').as_posix()}"


engine = create_async_engine(database_url(), pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def session() -> AsyncIterator[AsyncSession]:
    async with Session() as s:
        yield s


def backend_name() -> str:
    return engine.dialect.name
