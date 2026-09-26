import asyncio
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.services.http import close_client
from app.services.knowledge import CHUNKS, EMBED_META, EMBEDDERS, EMBEDDINGS, embed_texts

BATCH = {"mistral": 32, "gemini": 20}


async def embed_all(provider: str, rows: list[dict]) -> list[list[float]]:
    vectors: list[list[float]] = []
    size = BATCH[provider]
    for start in range(0, len(rows), size):
        texts = [f"{r['publisher']} — {r['title']}\n{r['text'][:6000]}" for r in rows[start:start + size]]
        for attempt in range(6):
            try:
                vectors += await embed_texts(provider, texts, "RETRIEVAL_DOCUMENT")
                break
            except Exception as exc:
                wait = 4 * (attempt + 1)
                print(f"  batch at {start} failed ({exc}); retrying in {wait}s", flush=True)
                await asyncio.sleep(wait)
        else:
            raise SystemExit("embedding failed repeatedly")
        print(f"embedded {min(start + size, len(rows))}/{len(rows)}", flush=True)
        await asyncio.sleep(1.2)
    return vectors


async def main() -> None:
    settings = get_settings()
    provider = sys.argv[1] if len(sys.argv) > 1 else ("mistral" if settings.mistral_api_key.strip() else "gemini")
    if provider not in EMBEDDERS:
        raise SystemExit(f"provider must be one of {list(EMBEDDERS)}")
    rows = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    vectors = await embed_all(provider, rows)
    await close_client()
    matrix = np.asarray(vectors, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
    np.save(EMBEDDINGS, matrix)
    EMBED_META.write_text(json.dumps({"provider": provider, **EMBEDDERS[provider], "ids": [r["id"] for r in rows]}), encoding="utf-8")
    print(f"saved {matrix.shape} with {provider} -> {EMBEDDINGS}")


if __name__ == "__main__":
    asyncio.run(main())
