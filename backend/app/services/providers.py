import asyncio
import json
from typing import Any, AsyncIterator, Protocol

import httpx

from app.config import get_settings
from app.services import tools
from app.services.http import client

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
RETRYABLE = (429, 500, 502, 503, 504)


class ProviderError(Exception):
    pass


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
    return [(t.get("role", "user"), (t.get("text") or "").strip()) for t in history[-12:] if (t.get("text") or "").strip()]


async def _post_stream(url: str, headers: dict[str, str], payload: dict[str, Any], params: dict[str, str] | None, label: str, retries: list[float]) -> AsyncIterator[str]:
    for attempt in range(len(retries) + 1):
        try:
            async with client().stream("POST", url, params=params, headers=headers, json=payload, timeout=httpx.Timeout(90, connect=15)) as response:
                if response.status_code in RETRYABLE and attempt < len(retries):
                    await response.aread()
                    await asyncio.sleep(retries[attempt])
                    continue
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="ignore")
                    raise ProviderError(f"{label} error {response.status_code}: {body[:300]}")
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

    def __init__(self, system: str, history: list[dict[str, str]], message: str, retries: list[float]):
        settings = get_settings()
        self.model = settings.gemini_model
        self.key = settings.gemini_api_key
        self.label = f"Gemini · {self.model}"
        self.retries = retries
        self.base = {
            "systemInstruction": {"parts": [{"text": system}]},
            "tools": [{"functionDeclarations": tools.TOOL_DECLARATIONS}],
            "generationConfig": {"temperature": 0.4},
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

    def __init__(self, system: str, history: list[dict[str, str]], message: str, retries: list[float]):
        settings = get_settings()
        self.model = settings.groq_model
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
        payload = {"model": self.model, "messages": self.messages, "tools": OPENAI_TOOLS, "tool_choice": "auto", "temperature": 0.4, "stream": True}
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


def available() -> list[type]:
    settings = get_settings()
    chain: list[type] = []
    if settings.gemini_api_key.strip():
        chain.append(Gemini)
    if settings.groq_api_key.strip():
        chain.append(Groq)
    return chain
