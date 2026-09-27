import asyncio
import json
import logging
from typing import Any

import asyncpg
from sqlalchemy import text

from app.db import Session, backend_name, database_url
from app.services.realtime import hub

log = logging.getLogger("weathergpt.fanout")

CHANNEL = "weathergpt_alerts"
SWEEP_S = 60


class Fanout:
    def __init__(self) -> None:
        self.listening = False
        self.received = 0
        self.published = 0
        self.last_error: str | None = None
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        if self._tasks:
            return
        if backend_name() == "postgresql":
            self._tasks.append(asyncio.create_task(self._listen(), name="fanout-listen"))
        self._tasks.append(asyncio.create_task(self._sweep(), name="fanout-sweep"))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.listening = False

    async def publish(self, clients: list[str] | None = None) -> None:
        self.published += 1
        if backend_name() == "postgresql":
            payload = json.dumps({"clients": clients})
            if len(payload) > 7000:
                payload = json.dumps({"clients": None})
            async with Session() as s:
                await s.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": CHANNEL, "payload": payload})
                await s.commit()
        if not self.listening:
            await self.dispatch(clients)

    async def dispatch(self, clients: list[str] | None = None) -> int:
        from app.services.ingest import notify_client
        from app.services.smart import stream

        targets = hub.client_ids() if clients is None else [c for c in clients if hub.online(c)]
        pushed = 0
        for client_id in targets:
            try:
                pushed += await notify_client(client_id)
                pushed += await stream(client_id)
            except Exception as exc:
                log.info("dispatch to %s failed: %s", client_id, exc)
        return pushed

    def _on_notify(self, connection: Any, pid: int, channel: str, payload: str) -> None:
        self.received += 1
        try:
            clients = json.loads(payload).get("clients")
        except ValueError:
            clients = None
        asyncio.get_running_loop().create_task(self.dispatch(clients))

    async def _listen(self) -> None:
        dsn = database_url().replace("postgresql+asyncpg://", "postgresql://", 1)
        delay = 2
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(dsn)
                await connection.add_listener(CHANNEL, self._on_notify)
                self.listening = True
                self.last_error = None
                delay = 2
                log.info("fanout listening on %s", CHANNEL)
                while not connection.is_closed():
                    await asyncio.sleep(5)
                    await connection.execute("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("fanout listener lost: %s", exc)
            finally:
                self.listening = False
                if connection is not None and not connection.is_closed():
                    await connection.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_S)
            await self.dispatch(None)

    def status(self) -> dict[str, Any]:
        return {
            "mode": "postgres-notify" if backend_name() == "postgresql" else "in-process",
            "listening": self.listening,
            "published": self.published,
            "received": self.received,
            "last_error": self.last_error,
        }


fanout = Fanout()
