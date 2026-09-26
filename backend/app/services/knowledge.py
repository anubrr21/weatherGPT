import json
import time
import logging
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.config import get_settings
from app.services.http import TTLCache, client

log = logging.getLogger("weathergpt.knowledge")
_query_vectors = TTLCache(ttl_s=3600, max_items=512)

KNOWLEDGE = Path(__file__).resolve().parent.parent.parent / "knowledge"
CHUNKS = KNOWLEDGE / "chunks.jsonl"
EMBEDDINGS = KNOWLEDGE / "embeddings.npy"
EMBED_META = KNOWLEDGE / "embedding_meta.json"
EMBEDDERS = {
    "mistral": {"model": "mistral-embed", "dims": 1024},
    "gemini": {"model": "gemini-embedding-2", "dims": 768},
}
RRF_K = 60
CANDIDATES = 40
K1 = 1.4
B = 0.75
PUBLIC_ADVICE_BOOST = 1.25
PHRASE_WEIGHT = 2.5

STOPWORDS = set(
    "a an and are as at be by for from has have how i if in into is it its of on or that the their them then there these "
    "this to was were what when where which who why will with do does did can could should would my me we you your our "
    "about during after before than so such not no yes any all also may might must shall very more most".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ies", "es", "s", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1]


class Index:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        streams = [tokenize(f"{r['title']} {r['text']}") for r in rows]
        self.docs = [Counter(tokenize(r["title"]) * 2 + stream) for r, stream in zip(rows, streams)]
        self.bigrams = [set(zip(stream, stream[1:])) for stream in streams]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lengths) / max(len(self.lengths), 1)
        df: Counter = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def score(self, i: int, terms: list[str]) -> float:
        doc, length = self.docs[i], self.lengths[i]
        total = 0.0
        for term in terms:
            tf = doc.get(term)
            if tf:
                total += self.idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self.avg))
        for pair in zip(terms, terms[1:]):
            if pair in self.bigrams[i]:
                total += PHRASE_WEIGHT * (self.idf.get(pair[0], 0) + self.idf.get(pair[1], 0)) / 2
        if self.rows[i]["publisher"].startswith("NDMA"):
            total *= PUBLIC_ADVICE_BOOST
        return total

    def keyword_ranking(self, query: str) -> list[int]:
        terms = tokenize(query)
        if not terms:
            return []
        scored = sorted(((self.score(i, terms), i) for i in range(len(self.rows))), reverse=True)
        return [i for value, i in scored[:CANDIDATES] if value > 0]

    def pick(self, fused: list[tuple[float, int]], k: int, per_source: int) -> list[dict[str, Any]]:
        picked: list[dict[str, Any]] = []
        used: Counter = Counter()
        for value, i in fused:
            if len(picked) >= k:
                break
            row = self.rows[i]
            if used[row["source_id"]] >= per_source:
                continue
            used[row["source_id"]] += 1
            picked.append({**row, "score": round(value, 4)})
        return picked

    def search(self, query: str, k: int = 5, per_source: int = 2) -> list[dict[str, Any]]:
        ranking = self.keyword_ranking(query)
        return self.pick([(1 / (RRF_K + r), i) for r, i in enumerate(ranking)], k, per_source)


@lru_cache
def index() -> Index | None:
    if not CHUNKS.exists():
        return None
    rows = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return Index(rows) if rows else None


@lru_cache
def embedding_meta() -> dict[str, Any] | None:
    if not EMBED_META.exists():
        return None
    return json.loads(EMBED_META.read_text(encoding="utf-8"))


@lru_cache
def vectors() -> np.ndarray | None:
    idx, meta = index(), embedding_meta()
    if idx is None or meta is None or not EMBEDDINGS.exists():
        return None
    if meta.get("ids") != [r["id"] for r in idx.rows]:
        log.warning("embeddings are out of date with chunks.jsonl; run scripts/embed_knowledge.py")
        return None
    return np.load(EMBEDDINGS)


async def embed_texts(provider: str, texts: list[str], task: str) -> list[list[float]]:
    settings = get_settings()
    spec = EMBEDDERS[provider]
    if provider == "mistral":
        response = await client().post(
            "https://api.mistral.ai/v1/embeddings",
            headers={"Authorization": f"Bearer {settings.mistral_api_key.strip()}"},
            json={"model": spec["model"], "input": texts},
            timeout=60,
        )
        response.raise_for_status()
        return [row["embedding"] for row in response.json()["data"]]
    response = await client().post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{spec['model']}:batchEmbedContents",
        headers={"x-goog-api-key": settings.gemini_api_key.strip()},
        json={"requests": [
            {"model": f"models/{spec['model']}", "content": {"parts": [{"text": t}]}, "taskType": task, "outputDimensionality": spec["dims"]}
            for t in texts
        ]},
        timeout=60,
    )
    response.raise_for_status()
    return [row["values"] for row in response.json()["embeddings"]]


async def _query_vector(query: str) -> np.ndarray | None:
    meta = embedding_meta()
    if not meta:
        return None

    async def load() -> np.ndarray:
        values = (await embed_texts(meta["provider"], [query], "RETRIEVAL_QUERY"))[0]
        vector = np.asarray(values, dtype=np.float32)
        return vector / (np.linalg.norm(vector) + 1e-9)

    try:
        return await _query_vectors.get_or_set(query.strip().lower(), load)
    except Exception as exc:
        log.warning("query embedding failed, using keyword search only: %s", exc)
        return None


EXPANSIONS = [
    (re.compile(r"(?i)(green|yellow|orange|red).*(alert|warning|code)|colou?r.?cod"), "colour coding hazardous conditions level green yellow orange red awareness potentially dangerous"),
    (re.compile(r"(?i)fisher|venture|boat"), "warnings for fisheries criteria fishermen advised not to venture sea"),
    (re.compile(r"(?i)heat ?wave"), "criteria for declaring heat wave maximum temperature departure from normal"),
    (re.compile(r"(?i)cold ?wave"), "criteria for declaring cold wave minimum temperature departure"),
    (re.compile(r"(?i)lightning|thunder"), "lightning safety shelter crouch 30/30 rule"),
    (re.compile(r"(?i)cyclone.*(categor|classif|type)|depression"), "classification of cyclonic disturbances wind speed knots"),
    (re.compile(r"(?i)heavy rain|rainfall (categor|intensity|terminology)"), "terminology rainfall intensity heavy very heavy extremely heavy mm"),
]


def expand(query: str) -> str:
    extra = [phrase for pattern, phrase in EXPANSIONS if pattern.search(query)]
    return f"{query} {' '.join(extra)}" if extra else query


async def search(query: str, k: int = 5, per_source: int = 3) -> list[dict[str, Any]]:
    idx = index()
    if idx is None:
        return []
    query = expand(query)
    fused: dict[int, float] = {}
    for rank, i in enumerate(idx.keyword_ranking(query)):
        fused[i] = fused.get(i, 0) + 1 / (RRF_K + rank)
    matrix = vectors()
    if matrix is not None:
        vector = await _query_vector(query)
        if vector is not None:
            sims = matrix @ vector
            for rank, i in enumerate(np.argsort(-sims)[:CANDIDATES]):
                fused[int(i)] = fused.get(int(i), 0) + 1.2 / (RRF_K + rank)
    return idx.pick(sorted(((v, i) for i, v in fused.items()), reverse=True), k, per_source)


def semantic_ready() -> bool:
    return vectors() is not None


_stats: tuple[float, dict[str, Any]] | None = None


def stats() -> dict[str, Any]:
    global _stats
    if _stats and time.monotonic() - _stats[0] < 300:
        return _stats[1]
    idx = index()
    value = {"chunks": 0, "sources": 0, "semantic": False} if not idx else {
        "chunks": len(idx.rows), "sources": len({r["source_id"] for r in idx.rows}), "semantic": semantic_ready(),
    }
    _stats = (time.monotonic(), value)
    return value
