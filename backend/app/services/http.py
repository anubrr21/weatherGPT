import asyncio
import time
from typing import Any, Awaitable, Callable

import httpx

from app.config import get_settings

_client: httpx.AsyncClient | None = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=get_settings().http_timeout_s,
            headers={"User-Agent": "WeatherGPT/0.1 (+https://github.com/anubrr21)"},
            follow_redirects=True,
        )
    return _client


async def get_retry(url: str, **kwargs: Any) -> httpx.Response:
    for attempt in range(3):
        try:
            response = await client().get(url, **kwargs)
            if response.status_code < 500 or attempt == 2:
                return response
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 2:
                raise
        await asyncio.sleep(0.6 * (attempt + 1))
    raise RuntimeError("unreachable")


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class TTLCache:
    def __init__(self, ttl_s: float, max_items: int = 512):
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self.ttl_s, value)

    async def get_or_set(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        hit = self._store.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._store.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            value = await factory()
            if len(self._store) >= self.max_items:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic() + self.ttl_s, value)
            return value


def coord_key(lat: float, lon: float, *extra: Any) -> str:
    return ":".join([f"{lat:.2f}", f"{lon:.2f}", *map(str, extra)])
