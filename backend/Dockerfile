ARG VOICES=full

FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM base AS voices-none
RUN mkdir -p /srv/models/tts

FROM base AS voices-full
COPY scripts/fetch_voices.py scripts/fetch_voices.py
RUN python scripts/fetch_voices.py

FROM voices-${VOICES} AS voices

FROM base AS runtime
RUN useradd --system --uid 10001 --home /srv weathergpt \
    && mkdir -p /srv/data \
    && chown weathergpt /srv/data
COPY --from=voices /srv/models /srv/models
COPY knowledge/chunks.jsonl knowledge/embeddings.npy knowledge/embedding_meta.json knowledge/sources.json knowledge/
COPY app app
USER weathergpt
ENV ROLE=all
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "20"]
