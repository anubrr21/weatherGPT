# WeatherGPT roadmap

## Phase 0 — Foundation ✅ (2026-09-26)

- FastAPI backend with live NWP (GFS / ECMWF / ICON / blended), geocoding and reverse geocoding
- Official IMD/NDMA CAP alert ingestion (SACHET RSS → CAP XML), matched to place
- Model-derived advisories using IMD thresholds
- ERA5 climate trends, CPCB-method NAQI, marine, METAR/TAF
- Gemini function-calling agent with SSE streaming, plus an offline intent fallback
- React + Vite mobile-first client: live sky canvas, 24 h radial time scrubber, 10-day strip, alert ribbon, streaming chat with data cards, 13 languages, voice in/out
- Verified end to end against live data sources

## Phase 1 — Intelligence and trust

- Hook up the Gemini key and test answers in all 13 languages (native script, spoken output)
- Better alert-to-place matching: district alias table (e.g. Purba Bardhaman ↔ East Burdwan) and CAP polygon geometry where available
- Sector advisory engines: crop-weather (crop stage, spray windows, irrigation from ET₀), fisher go/no-go, aviation briefing format, urban heat and waterlogging
- Forecast-confidence scoring from the model spread, shown in answers
- Conversation memory for the user's role, crops and saved places

## Phase 2 — Real-time ingestion and scale

- Background ingestion workers for the CAP feed and model runs, with push when a new warning hits a saved place
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
