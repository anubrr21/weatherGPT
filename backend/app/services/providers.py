import asyncio
import json
import re
import time
from typing import Any, AsyncIterator, Protocol

import httpx

from app.config import get_settings
from app.services import tools
from app.services.http import client

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
RETRYABLE = (429, 500, 502, 503, 504)


class ProviderError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


_cooldown: dict[str, float] = {}
_strikes: dict[str, int] = {}


def parse_retry_after(body: str) -> float | None:
    match = re.search(r"(?:retry in|try again in)\s+(?:(\d+)m)?([\d.]+)s", body, re.I)
    if not match:
        return None
    return int(match.group(1) or 0) * 60 + float(match.group(2))


def bench(key: str, error: Exception) -> None:
    strikes = _strikes.get(key, 0) + 1
    _strikes[key] = strikes
    if isinstance(error, ProviderError) and error.status == 429 and key.startswith("groq:") and error.retry_after:
        _cooldown[key] = time.monotonic() + error.retry_after + 1
        return
    if isinstance(error, ProviderError) and error.status == 429:
        base = max(error.retry_after or 60, 60)
        if "per day" in str(error).lower() or "perday" in str(error).lower():
            base = 3600
    elif isinstance(error, ProviderError) and error.status in (400, 401, 403, 404):
        base = 3600
    else:
        base = 30
    _cooldown[key] = time.monotonic() + min(base * 2 ** (strikes - 1), 3 * 3600)


def succeeded(key: str) -> None:
    _strikes.pop(key, None)
    _cooldown.pop(key, None)


def cooling(key: str) -> float:
    return max(0.0, _cooldown.get(key, 0) - time.monotonic())


class Call(dict):
    @property
    def name(self) -> str:
        return self["name"]

    @property
    def args(self) -> dict[str, Any]:
        return self.get("args") or {}


class Provider(Protocol):
    name: str
    label: str

    def turn(self) -> AsyncIterator[tuple[str, Any]]: ...

    def add_results(self, calls: list[Call], results: list[dict[str, Any]]) -> None: ...


def _history(history: list[dict[str, str]]) -> list[tuple[str, str]]:
    return [(t.get("role", "user"), (t.get("text") or "").strip()[:1500]) for t in history[-10:] if (t.get("text") or "").strip()]


async def _post_stream(url: str, headers: dict[str, str], payload: dict[str, Any], params: dict[str, str] | None, label: str, retries: list[float]) -> AsyncIterator[str]:
    timeout = httpx.Timeout(60 if retries else 12, connect=8)
    for attempt in range(len(retries) + 1):
        try:
            async with client().stream("POST", url, params=params, headers=headers, json=payload, timeout=timeout) as response:
                if response.status_code in RETRYABLE and attempt < len(retries):
                    await response.aread()
                    await asyncio.sleep(retries[attempt])
                    continue
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="ignore")
                    raise ProviderError(f"{label} error {response.status_code}: {body[:300]}", response.status_code, parse_retry_after(body))
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        chunk = line[5:].strip()
                        if chunk and chunk != "[DONE]":
                            yield chunk
                return
        except httpx.HTTPError as exc:
            if attempt < len(retries):
                await asyncio.sleep(retries[attempt])
                continue
            raise ProviderError(f"{label} unreachable: {type(exc).__name__}") from exc


class Gemini:
    name = "gemini"

    def __init__(self, model: str, system: str, history: list[dict[str, str]], message: str, retries: list[float]):
        settings = get_settings()
        self.model = model
        self.key = settings.gemini_api_key
        self.label = f"Gemini · {self.model}"
        self.retries = retries
        self.base = {
            "systemInstruction": {"parts": [{"text": system}]},
            "tools": [{"functionDeclarations": tools.TOOL_DECLARATIONS}],
            "generationConfig": {"temperature": 0.4, "thinkingConfig": {"thinkingLevel": "low"}},
        }
        self.contents = [{"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]} for role, text in _history(history)]
        self.contents.append({"role": "user", "parts": [{"text": message}]})

    async def turn(self) -> AsyncIterator[tuple[str, Any]]:
        parts: list[dict[str, Any]] = []
        async for chunk in _post_stream(
            GEMINI_URL.format(model=self.model), {"x-goog-api-key": self.key}, {**self.base, "contents": self.contents}, {"alt": "sse"}, "Gemini", self.retries
        ):
            data = json.loads(chunk)
            for candidate in data.get("candidates", [])[:1]:
                for part in candidate.get("content", {}).get("parts", []):
                    parts.append(part)
                    if "functionCall" in part:
                        yield "call", Call(name=part["functionCall"]["name"], args=part["functionCall"].get("args") or {})
                    elif part.get("text") and not part.get("thought"):
                        yield "text", part["text"]
        self.contents.append({"role": "model", "parts": parts or [{"text": ""}]})

    def add_results(self, calls: list[Call], results: list[dict[str, Any]]) -> None:
        self.contents.append({"role": "user", "parts": [{"functionResponse": {"name": c.name, "response": r}} for c, r in zip(calls, results)]})


def _json_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: (v.lower() if k == "type" and isinstance(v, str) else _json_schema(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_json_schema(v) for v in node]
    return node


OPENAI_TOOLS = [
    {"type": "function", "function": {"name": d["name"], "description": d["description"], "parameters": _json_schema(d["parameters"])}}
    for d in tools.TOOL_DECLARATIONS
]


class Groq:
    name = "groq"

    def __init__(self, model: str, system: str, history: list[dict[str, str]], message: str, retries: list[float]):
        settings = get_settings()
        self.model = model
        self.key = settings.groq_api_key
        self.label = f"Groq · {self.model}"
        self.retries = retries
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.messages += [{"role": "assistant" if role == "assistant" else "user", "content": text} for role, text in _history(history)]
        self.messages.append({"role": "user", "content": message})
        self.pending_ids: list[str] = []

    async def turn(self) -> AsyncIterator[tuple[str, Any]]:
        text = ""
        slots: dict[int, dict[str, str]] = {}
        payload: dict[str, Any] = {"model": self.model, "messages": self.messages, "tools": OPENAI_TOOLS, "tool_choice": "auto", "temperature": 0.4, "stream": True}
        if "gpt-oss" in self.model:
            payload["reasoning_effort"] = "low"
        async for chunk in _post_stream(GROQ_URL, {"Authorization": f"Bearer {self.key}"}, payload, None, "Groq", self.retries):
            data = json.loads(chunk)
            if data.get("error"):
                raise ProviderError(f"Groq error: {data['error']}")
            for choice in data.get("choices", [])[:1]:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text += delta["content"]
                    yield "text", delta["content"]
                for tc in delta.get("tool_calls") or []:
                    slot = slots.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                    slot["id"] = tc.get("id") or slot["id"]
                    fn = tc.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    slot["arguments"] += fn.get("arguments") or ""
        ordered = [slots[i] for i in sorted(slots)]
        for i, slot in enumerate(ordered):
            slot["id"] = slot["id"] or f"call_{len(self.messages)}_{i}"
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if ordered:
            message["tool_calls"] = [
                {"id": s["id"], "type": "function", "function": {"name": s["name"], "arguments": s["arguments"] or "{}"}} for s in ordered
            ]
        self.messages.append(message)
        self.pending_ids = [s["id"] for s in ordered]
        for slot in ordered:
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield "call", Call(name=slot["name"], args=args if isinstance(args, dict) else {})

    def add_results(self, calls: list[Call], results: list[dict[str, Any]]) -> None:
        for call_id, result in zip(self.pending_ids, results):
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(result, ensure_ascii=False, default=str)})


def chain() -> list[tuple[type, str]]:
    settings = get_settings()
    pools = {"gemini": (Gemini, settings.gemini_models), "groq": (Groq, settings.groq_models)}
    ordered: list[tuple[type, str]] = []
    for slot in settings.model_order.split(","):
        name, _, index = slot.strip().partition(":")
        cls, models = pools.get(name, (None, []))
        if cls and index.isdigit() and int(index) < len(models):
            ordered.append((cls, models[int(index)]))
    for cls, models in pools.values():
        ordered += [(cls, m) for m in models if (cls, m) not in ordered]
    return ordered


def available() -> list[tuple[type, str]]:
    return [(cls, model) for cls, model in chain() if not cooling(f"{cls.name}:{model}")]


def soonest_free() -> float | None:
    waits = [cooling(f"{cls.name}:{model}") for cls, model in chain()]
    return min(waits) if waits else None
