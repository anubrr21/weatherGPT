# WeatherGPT roadmap

## Phase 0 — Foundation ✅ (2026-09-26)

- FastAPI backend with live NWP (GFS / ECMWF / ICON / blended), geocoding and reverse geocoding
- Official IMD/NDMA CAP alert ingestion (SACHET RSS → CAP XML), matched to place
- Model-derived advisories using IMD thresholds
- ERA5 climate trends, CPCB-method NAQI, marine, METAR/TAF
- Gemini function-calling agent with SSE streaming, plus an offline intent fallback
- React + Vite mobile-first client: live sky canvas, 24 h radial time scrubber, 10-day strip, alert ribbon, streaming chat with data cards, 13 languages, voice in/out
- Verified end to end against live data sources

## Phase 1 — Intelligence and trust (in progress, 2026-09-26)

Done and verified against live data:
- Sector advisory engines (`backend/app/services/advisory.py`)
  - Farm: spray windows (wind 3–15 km/h, gust <25, no rain ≥30% within 6 h, ≤32 °C, RH ≥35%, daylight), 7-day irrigation balance (FAO-56 Kc × ET₀ minus effective rain, 14 crops × 4 stages), dry spells for harvest, livestock THI, heavy-rain days
  - Fishing: GO / CAUTION / NO-GO now and for 5 days from waves, gusts and official sea/cyclone warnings
  - City: NOAA heat index curve and band, waterlogging risk from hourly and 3-hourly rain intensity, commute slots
  - Aviation: decoded METAR (wind, visibility, weather, cloud incl. CB/TCU, QNH, trend, hazards)
- Forecast confidence per day from GFS/ECMWF/ICON spread, rain-vote agreement and lead time; shown on forecast cards and given to the LLM
- Alert matching: word-boundary matching, diacritics stripped, Purba/Paschim → East/West, ~45 district alias groups (Burdwan, Baleshwar/Balasore, Gurugram/Gurgaon…)
- User profile (role, crops + stage, saved places, notes), stored on device, sent with every chat; the LLM can update it through `update_profile`
- Role-aware home briefing (`/api/insights`) and profile sheet
- Offline mode handles farm/fishing/city/aviation intents, crop keywords and better place extraction
- LLM provider chain Gemini -> Groq (openai/gpt-oss-120b) -> offline intent engine; a provider failing mid-answer emits reset and the next one answers cleanly; verified with invalid keys and a simulated mid-stream failure

- Model rotation across 5 free-tier models (Gemini 3.8 flash → 3.7 flash → 3.5 flash-lite → Groq gpt-oss-120b → gpt-oss-20b). Each model is benched on 429/503 with escalating backoff; 30 s stall timeout; waits up to 20 s for capacity before degrading; low thinking effort on both providers
- Multilingual eval (`backend/eval_languages.py --pace=15`, 15 questions in 13 languages incl. farm and fishing): 14/15 pass (native script, real tool use), median 7.7 s total. The one miss was every model rate-limited after three back-to-back eval runs. Prompt tuned from the answers: calibrated rain wording, confidence stated as a score, condition labels translated

Still open:
- Free-tier capacity is the real constraint (gemini-3.8-flash allows ~20 requests on this key). Before a demo, don't run evals; consider a paid tier or more Groq models
- CAP polygon geometry (the SACHET polygon endpoint returns 403 today)

## Phase 2 — Real-time ingestion and scale (in progress, 2026-09-27)

Phase 2a done:
- Database layer (SQLAlchemy async): SQLite by default, PostgreSQL via `DATABASE_URL` (asyncpg). Tables for alerts (full history with first/last seen), subscriptions, deliveries (no duplicate notifications), station observations, ingest runs
- Background workers in the API process: IMD/NDMA CAP feed every 2 min (new-alert detection, verified: 32 stored, second run 0 new), METAR observations across India every 15 min (30-day history), forecast warm-up for subscribed places every 30 min; each run logged with status
- WebSocket `/ws` live push: new alerts matched to a client's saved places are pushed instantly, missed ones are delivered on reconnect, each alert delivered once per client
- API: `PUT /api/subscriptions`, `GET /api/alerts/history`, `GET /api/observations/nearby`, `GET /api/system/status`
- Frontend: live bell with connection state, unread badge and inbox; alert banners; desktop notifications (permission on request); tapping an alert asks the assistant what to do. Verified in the browser with real IMD alerts for Jaipur

Still in Phase 2:
- Background ingestion workers for the CAP feed and model runs, with push when a new warning hits a saved place — done (above)
- Explore MQTT / WIS 2.0 subscriptions for WMO real-time data
- PostgreSQL + PostGIS for places, alert polygons and history; Redis cache
- WebSocket channel for live alert push
- Docker Compose, then Kubernetes manifests; load test for latency targets

## Phase 3 — Mobile app and rural voice

- Package as an Android app (Capacitor), with push notifications for warnings
- Server-side neural STT/TTS for Indian languages (reuse iTantra's IndicConformer / Piper work) so voice works on low-end phones and without Google speech
- Low-bandwidth mode, offline last-known forecast, SMS/IVR fallback for feature phones

## Phase 4 — Maps and GIS

- Radar/satellite and model field layers (rain, wind, temperature) on a map
- Cyclone track visualisation; district-level warning map

## Phase 5 — Evaluation

- Accuracy: forecast verification against observations; answer grounding checks
- Latency: measured p50/p95 for first token and full answer
- Multilingual quality review with native speakers
