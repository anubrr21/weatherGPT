# Deployment

WeatherGPT ships as two images and runs in three roles.

| Image | Contents |
| --- | --- |
| `weathergpt-api` | FastAPI backend, RAG index, optional Piper voices (`VOICES=full` adds ~540 MB, `VOICES=none` skips them) |
| `weathergpt-web` | Built React app on unprivileged nginx; proxies `/api`, streaming `/api/chat` and `/ws` to the API |

| Role (`ROLE`) | What it runs |
| --- | --- |
| `api` | HTTP API and WebSocket push. Stateless, scale horizontally |
| `worker` | IMD/NDMA CAP ingestion, METAR ingestion, forecast warm-up, WMO WIS2 subscriber. Exactly one replica |
| `all` | Everything in one process (local development) |

## How alerts reach users across replicas

The worker stores a new warning and runs `pg_notify('weathergpt_alerts', …)`. Every API pod keeps a `LISTEN` connection. When a notification arrives, each pod checks the warning against the saved places of the clients connected to it and pushes it over their WebSocket. Deliveries are recorded per client. A client that was offline gets its missed warnings when it reconnects, and each warning is delivered only once. A 60-second sweep covers any notification lost while a listener was reconnecting. No Redis or sticky sessions are needed.

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

Put the real `POSTGRES_PASSWORD` in `.env` and keep using URL-safe characters. The LLM and voice keys come from `backend/.env`. The app is served on `http://localhost:8080` with Postgres, one worker and `API_REPLICAS` API containers (default 2).

## Kubernetes

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl -n weathergpt create secret generic weathergpt-secrets --from-env-file=backend/.env --from-literal=POSTGRES_PASSWORD=... --from-literal=DATABASE_URL=postgresql+asyncpg://weathergpt:...@weathergpt-db:5432/weathergpt
kubectl apply -k deploy/k8s
```

- `api`: 2–10 pods through a CPU-based HorizontalPodAutoscaler, rolling updates with zero unavailable, a PodDisruptionBudget, and startup, readiness (`/api/ready`, checks the database) and liveness (`/api/health`) probes.
- `worker`: 1 pod with the `Recreate` strategy, so two WIS2 subscribers never run at the same time.
- `web`: 2 nginx pods.
- `ingress`: sends `/api` and `/ws` straight to the API with one-hour timeouts and no buffering, for WebSockets and streamed answers, and TLS through cert-manager.
- Everything runs as non-root with all capabilities dropped and the default seccomp profile.
- `postgres.yaml` is a single-instance StatefulSet for demos. In production, point `DATABASE_URL` at a managed Postgres instead.

CI (`.github/workflows/ci.yml`) runs the backend tests and the frontend build on every push. On `main` it builds both images and publishes them to GHCR. `deploy/k8s/kustomization.yaml` points at those images.

## Android app and push

```bash
cd frontend
npm run android:run -- --api https://weathergpt.example.in
```

- Without `--api` the app talks to `http://localhost:8000` through `adb reverse`, which is enough for a phone on USB.
- Push needs a Firebase project. Put `google-services.json` (Android app `in.weathergpt.app`) in `frontend/android/app/`. Give the backend the service account via `FCM_SERVICE_ACCOUNT`, either a path relative to `backend/` (for example `secrets/firebase-service-account.json`, which is git-ignored) or the JSON itself (for a Kubernetes secret).
- Only the worker sends pushes, when it stores a new warning. `POST /api/devices/test {client_id}` sends a test notification to a client's phones.

## Speech models

```bash
cd backend
python scripts/fetch_stt_models.py --indic-from <folder with the IndicConformer ONNX bundle>
```

- The models live in `backend/models/stt` (git-ignored, about 1 GB). Without them, speech recognition falls back to Groq only.
- In containers, mount them at `/srv/models/stt`. With IndicConformer loaded, an API process uses about 1.3 GB more RAM, so the API pods request 1.5 Gi and are limited to 3 Gi.

## Load test

```bash
cd backend
python loadtest/loadtest.py --base http://127.0.0.1:8000 --duration 30 --concurrency 50 --ws 200
```

- Traffic mix: 40% forecast, 20% alerts, 15% station observations, 10% geocode, 10% reverse geocode, 5% health.
- 20 Indian cities, after a warm-up pass.
- The load generator runs in several processes and reports its own CPU use, so it doesn't become the bottleneck.
- Reports p50, p95 and p99 per endpoint, throughput and error rate, WebSocket connect time and whether sockets stayed open.
- Exits non-zero if p95 exceeds `--target-p95` (default 300 ms) or errors reach 1%.

Results on a laptop (16 threads, Windows, one API process without uvloop, PostgreSQL 17, cached upstream data):

| Run | Throughput | p50 | p95 | p99 | Errors | WebSockets |
| --- | --- | --- | --- | --- | --- | --- |
| 50 users + 200 sockets, 30 s | 525 req/s | 78 ms | 148 ms | 182 ms | 0 | 200/200 held |
| 150 users, 20 s (saturation) | 476 req/s | 229 ms | 461 ms | 1239 ms | 0 | — |

One API process saturates at about 500 req/s. Past that point latency grows, but requests don't fail. On Linux the image adds uvloop, and the autoscaler adds pods as load rises. Raw results are in `backend/loadtest/results/`.
