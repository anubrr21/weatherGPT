# WeatherGPT

Conversational weather intelligence for India.

Ask about the weather by voice or text in 13 Indian languages. Answers are grounded in live data: numerical weather prediction models, official IMD/NDMA warnings, 35 years of climate reanalysis, air quality, sea state and aviation reports. Replies come with rich cards.

## What is real today

| Capability | Source |
|---|---|
| Current + 48 h hourly + 10-day forecast | Open-Meteo: blended, **NOAA GFS**, **ECMWF IFS 0.25°**, **DWD ICON** |
| Model disagreement / forecast confidence | GFS vs ECMWF vs ICON side by side with spread |
| Official warnings | **NDMA SACHET CAP feed** (IMD + state SDMAs), matched to district/state |
| Model-derived advisories | IMD thresholds (heavy rain ≥64.5 mm, very heavy ≥115.6, extremely heavy ≥204.5, heat wave, cold wave, gusts, thunderstorm, fog) |
| Climate trends | ERA5 reanalysis 1991→present: warming stripes, °C/decade, rainfall trend, month vs 1991–2020 normal |
| Air quality | India **NAQI** computed with the CPCB sub-index method from 24 h PM2.5/PM10 |
| Marine | Wave height, swell, period, SST, go/no-go sea state |
| Aviation | Live **METAR/TAF** from aviationweather.gov |
| Conversational AI | Function-calling agent over the tools above, streamed (SSE). Provider chain: **Gemini → Groq (gpt-oss-120b) → offline intent engine**; a provider failing mid-answer is discarded and the next one answers cleanly |
| Voice | Web Speech API speech-to-text and text-to-speech in the selected language |
| Knowledge (RAG) | 24 official documents — IMD SOPs (forecasting & warnings, cyclone, agromet GKMS, aviation), RSMC cyclone terminology, IMD health bulletin, NDMA hazard guidance and Do's & Don'ts, NDMA thunderstorm/lightning guidelines — 1,259 cited passages, hybrid keyword (BM25) + multilingual semantic search (Mistral embeddings) with rank fusion |
| Observations | Nearest real station report (METAR) shown next to the model forecast |
| Radar | Live 2-hour precipitation radar loop (RainViewer) |

## Run it

Backend (Python 3.12+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

Keys go in `backend/.env` (all optional, any one enables the AI; more keys = more free capacity):

| Key | Used for | Get it at |
|---|---|---|
| `GEMINI_API_KEY` | LLM + cloud voice for languages without a local voice | aistudio.google.com |
| `GROQ_API_KEY` | LLM + Whisper speech-to-text | console.groq.com |
| `CEREBRAS_API_KEY` | LLM (fast, OpenAI-compatible) | cloud.cerebras.ai |
| `MISTRAL_API_KEY` | LLM (strong multilingual) | console.mistral.ai |
| `OPENROUTER_API_KEY` | LLM (free `:free` models) | openrouter.ai |
| `SARVAM_API_KEY` | Natural Indian voices incl. Tamil, Kannada, Gujarati, Punjabi, Odia | dashboard.sarvam.ai |
| `AZURE_SPEECH_KEY` | Optional neural voices, all 13 languages | portal.azure.com |

Requests rotate across every configured provider; a rate-limited model is benched for exactly the time the provider asks, and the same question from the same place within 10 minutes is served from cache.

Offline voices (Hindi, Telugu, Malayalam, Marathi, Bengali, Urdu, English — unlimited, no key): `backend/.venv/Scripts/python backend/scripts/fetch_voices.py`

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5180. On a phone on the same Wi-Fi, use the laptop's LAN IP on port 5180.

## Layout

```
backend/app/
  main.py              FastAPI routes: /api/weather /api/alerts /api/climate /api/air /api/models /api/chat …
  services/weather.py  NWP, geocoding, AQI, climate, marine, METAR clients (cached)
  services/alerts.py   CAP feed ingestion + place matching + IMD-threshold advisories
  services/tools.py    Tool layer shared by the LLM agent and offline mode
  services/agent.py    Gemini streaming tool-calling loop + offline intent engine
frontend/src/
  components/SkyCanvas.tsx  Live sky rendered from real conditions
  components/TimeDial.tsx   24 h radial scrubber (temperature ring, rain spokes, day/night)
  components/Chat.tsx       Streaming chat, voice in/out, language switch
  components/cards/         Forecast, alerts, climate stripes, model spread, AQI, marine, METAR
```

See [docs/ROADMAP.md](docs/ROADMAP.md) for the phased plan.

## Knowledge base

The assistant answers definitions, criteria, colour codes and safety advice only from official documents, and cites them.

```bash
backend/.venv/Scripts/python backend/scripts/build_knowledge.py
backend/.venv/Scripts/python backend/scripts/embed_knowledge.py mistral
```

`backend/knowledge/sources.json` lists every document with its official URL. Raw downloads stay in `backend/knowledge/raw/` (gitignored); `chunks.jsonl` and the embeddings are committed so the app works without rebuilding.
