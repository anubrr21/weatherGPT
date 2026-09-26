import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("weathergpt.realtime")


class Hub:
    def __init__(self) -> None:
        self._clients: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def join(self, client_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._clients[client_id].add(socket)

    async def leave(self, client_id: str, socket: WebSocket) -> None:
        async with self._lock:
            self._clients[client_id].discard(socket)
            if not self._clients[client_id]:
                self._clients.pop(client_id, None)

    def online(self, client_id: str) -> bool:
        return bool(self._clients.get(client_id))

    def client_ids(self) -> list[str]:
        return list(self._clients)

    def stats(self) -> dict[str, int]:
        return {"clients": len(self._clients), "sockets": sum(len(s) for s in self._clients.values())}

    async def send(self, client_id: str, event: dict[str, Any]) -> int:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        sent = 0
        for socket in list(self._clients.get(client_id, ())):
            try:
                await socket.send_text(payload)
                sent += 1
            except Exception as exc:
                log.info("dropping dead socket for %s: %s", client_id, exc)
                await self.leave(client_id, socket)
        return sent

    async def broadcast(self, event: dict[str, Any]) -> int:
        total = 0
        for client_id in list(self._clients):
            total += await self.send(client_id, event)
        return total


hub = Hub()
