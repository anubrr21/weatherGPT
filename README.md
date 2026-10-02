# WeatherGPT

A weather assistant for India. It takes official warnings from IMD, NDMA and the state disaster authorities, forecasts from several global models and live station observations, and explains them in plain language for one place and one person: a farmer, a fisher, a pilot, a commuter, a district officer.

You can ask it questions by text or voice in 13 Indian languages, get warnings on your phone before the weather arrives, plan a journey around the weather, and reach it from a keypad phone by SMS or a voice call.

## What it does

**Weather for a place**
- Current conditions, 48 hours by the hour and 10 days ahead from a blend of GFS, ECMWF IFS and ICON, shown next to the nearest real IMD station reading.
- Official warnings for the district, with the area they cover.
- Rain radar and satellite rain for the last two hours.

**Ask in your own language**
- A chat assistant that answers from live data rather than from memory. It can look up forecasts, warnings, climate records, air quality, sea state, airport reports, cyclones, lightning, trips and forecast accuracy, and it quotes IMD and NDMA documents for official guidance.
- Text or voice, in English, Hindi, Bengali, Telugu, Tamil, Marathi, Gujarati, Kannada, Malayalam, Odia, Punjabi, Assamese and Urdu. Speech recognition for the Indian languages and text-to-speech run on the server.

**Warnings that come to you**
- Push notifications for official warnings, cyclones approaching a saved place, rain starting soon, thunderstorms, lightning nearby, heat, wind, fog and a morning briefing, written in the user's language.
- Quiet hours and a daily cap, with severe warnings always delivered.

**Keypad phones**
- SMS commands (`WEATHER <PIN code>`, `JOIN <place>`, `LANG TE`, `STOP`) and free-form questions.
- A voice helpline driven by number keys: language, PIN code, then weather, warnings, farm advice or subscribe.
- Automatic warning SMS, and a voice call when a warning is severe.
- A simulator at `/phone` stands in for a telecom provider during development. A Twilio adapter is included.

**Trip planner**
- Real routes for car, two-wheeler, bus, train, flight and trek, with stops on the way.
- Weather at each point of the route at the time you will be there, the best time to leave, rest stops and places along the road.

**Hazard tabs**
- *Maps*: animated wind, temperature, rain, cloud and pressure over India for 48 hours, and every live warning polygon.
- *Cyclones*: live storms with track, forecast cone and wind zones, closest approach to your place, cyclone history since 1980, shelters.
- *Lightning*: official lightning and thunderstorm warning areas, live strikes, a thunderstorm outlook and safety guidance.
- *Accuracy*: nine forecast models checked against airport observations near you.

**A workspace for your job**

Set your role in the profile and an extra tab appears:

| Role | Tab | Contents |
|---|---|---|
| Farmer | Farm | Seven-day field plan, spray and irrigation days, disease weather, water budget, soil temperature and moisture |
| Fisher | Sea | Go or no-go by boat type, waves, swell, currents, tides |
| Aviation | Aviation | Decoded METAR and TAF, runway wind components, density altitude, winds aloft, SIGMETs |
| City | City | Commute, waterlogging, heat stress, air quality, best time outdoors |
| Disaster management | Command | Towns ranked by risk, warning areas, population exposed, situation report |
| Researcher | Data | Model comparison, climate trends, station observations, CSV downloads |

**Offline and low bandwidth**
- The last forecast, warnings and notices for each place are kept on the device.
- A data saver mode switches on by itself on slow connections.

## How it is built

```
Android app (Capacitor)  ┐
Web app (React)          ├──►  FastAPI server  ──►  LLM providers, speech models
Keypad phone (SMS, IVR)  ┘          │
                                    ├──►  PostgreSQL
                         Worker ────┘     (warnings, places, notices, messages)
                         (ingest, alerts)
```

| Part | Technology |
|---|---|
| Web app | React 19, TypeScript, Vite, Leaflet |
| Android app | Capacitor 8, Firebase Cloud Messaging |
| Server | Python 3.14, FastAPI, SQLAlchemy, httpx |
| Database | PostgreSQL (SQLite for local development) |
| Assistant | Tool-calling agent over Cerebras, Groq, Gemini, Mistral and OpenRouter with automatic fallback |
| Speech | IndicConformer and Whisper for recognition, Piper voices for speech, both through ONNX Runtime |
| Document search | BM25 and embeddings over IMD and NDMA documents |
| Live updates | WebSockets, PostgreSQL LISTEN/NOTIFY |

The server runs in three roles set by `ROLE`: `api`, `worker` or `all`. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Docker Compose and Kubernetes.

## Data sources

| Data | Source |
|---|---|
| Official warnings | NDMA SACHET CAP feed (IMD, CWC, state disaster authorities) |
| Station observations | IMD through the WMO WIS 2.0 network; airport METAR and TAF from the Aviation Weather Center |
| Forecasts, marine, air quality | Open-Meteo (GFS, ECMWF IFS, ICON and others) |
| Climate | ERA5 reanalysis |
| Cyclones | GDACS, JTWC, IMD RSMC New Delhi bulletins, IBTrACS |
| Lightning strikes | Blitzortung.org, non-commercial use |
| Radar and satellite rain | RainViewer, NASA GPM |
| Roads, railways, towns, shelters | OpenStreetMap, OSRM, OurAirports |

## Running it

Backend:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

On Linux or macOS use `.venv/bin/` instead of `.venv/Scripts/`.

The assistant needs at least one LLM key in `backend/.env`. All keys are optional and each one adds capacity:

| Key | Used for |
|---|---|
| `CEREBRAS_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | Chat |
| `GROQ_API_KEY` | Speech recognition fallback |
| `SARVAM_API_KEY`, `AZURE_SPEECH_KEY`, `GEMINI_API_KEY` | Cloud voices for languages without a local voice |

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5180.

Android:

```bash
cd frontend
npm run android:run
```

This builds the web app, syncs the Capacitor project and installs the debug APK on a connected phone. Push notifications need your own `google-services.json` and a Firebase service account.

## Optional data

The app runs without these; the features that need them say so when the data is missing.

```bash
cd backend
.venv/Scripts/python scripts/fetch_voices.py
.venv/Scripts/python scripts/fetch_stt_models.py
.venv/Scripts/python scripts/build_cyclone_history.py
.venv/Scripts/python scripts/build_rail_graph.py
.venv/Scripts/python scripts/build_shelters.py
```

The last two read `backend/data/rail/india-latest.osm.pbf` from the [Geofabrik India extract](https://download.geofabrik.de/asia/india.html) and need `pip install osmium`.

## Tests

```bash
cd backend
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q tests
```

## Layout

```
backend/app/            FastAPI app, routes and services
backend/app/services/   weather, alerts, agent, trips, cyclones, lightning, verify, farm, sea, aviation, city, command, research, phone, ivr
backend/knowledge/      indexed IMD and NDMA documents
backend/scripts/        data builders
backend/tests/          unit tests
frontend/src/           React app
frontend/android/       Capacitor Android project
deploy/k8s/             Kubernetes manifests
docs/                   deployment notes and roadmap
```

## Notes

- WeatherGPT explains official information; it does not replace it. For evacuation and emergencies follow IMD and the district administration.
- Disease risk in the Farm tab means the weather favours a disease. It is not a diagnosis.
- Boat limits in the Sea tab are rule-of-thumb thresholds. An official fishermen warning always overrides them.
- The Aviation tab is for planning support, not a substitute for an official briefing.
- Sending real SMS in India needs a provider account and DLT registration.
