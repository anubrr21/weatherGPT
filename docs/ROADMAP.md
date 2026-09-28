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

## Phase 2 — Real-time ingestion and scale (done, 2026-09-27)

Phase 2a done:
- Database layer (SQLAlchemy async): SQLite by default, PostgreSQL via `DATABASE_URL` (asyncpg). Tables for alerts (full history with first/last seen), subscriptions, deliveries (no duplicate notifications), station observations, ingest runs
- Background workers in the API process: IMD/NDMA CAP feed every 2 min (new-alert detection, verified: 32 stored, second run 0 new), METAR observations across India every 15 min (30-day history), forecast warm-up for subscribed places every 30 min; each run logged with status
- WebSocket `/ws` live push: new alerts matched to a client's saved places are pushed instantly, missed ones are delivered on reconnect, each alert delivered once per client
- API: `PUT /api/subscriptions`, `GET /api/alerts/history`, `GET /api/observations/nearby`, `GET /api/system/status`
- Frontend: live bell with connection state, unread badge and inbox; alert banners; desktop notifications (permission on request); tapping an alert asks the assistant what to do. Verified in the browser with real IMD alerts for Jaipur

Phase 2b done:
- WMO WIS 2.0 subscription over MQTT (Météo-France global broker, TLS): the full global notification stream (about 1,000 messages a minute), with every India-related message stored (IMD's own `in-imd` node plus GTS bulletins with area IN relayed by DWD and JMA)
- IMD's native WIS2 node publishes hourly per-station BUFR4 SYNOP; these are downloaded and decoded in pure Python (pybufrkit), giving temperature, dew point, humidity, pressure, wind, visibility, cloud and present weather. A 6-hour backfill runs on startup
- FM-12 SYNOP text decoder for GTS bulletins (SMIN/SIIN/SNIN), with a 372-station Indian WMO catalogue for coordinates
- IMD's server omits its emSign intermediate certificate, so the public intermediate is bundled and added to the trust store. Verification stays on and chains still have to end at a certifi root
- About 93 IMD surface stations per synoptic hour now sit next to about 26 airport METARs. The "Measured" reading and the assistant use whichever real station is closest and fresh, labelled IMD station or METAR (for example Bahraich 42273 at 1 km)
- Duplicate re-issued CAP bulletins (same text and expiry under a new ID) are collapsed, so each warning is notified once
- `GET /api/wis2/status` reports broker state, message rate, per-centre counts and decode stats
- Tests: SYNOP decoding, topic parsing, BUFR decoding on a real IMD Nashik file, alert dedup

Phase 2c done (details in [DEPLOYMENT.md](DEPLOYMENT.md)):
- The API and the ingestion worker split into roles (`ROLE=api|worker|all`). API pods are stateless and scale out; one worker pod does ingestion and WIS2
- Alerts fan out across replicas with PostgreSQL LISTEN/NOTIFY: a warning found by the worker is pushed from whichever API pod holds the user's socket. Verified with two live processes. No Redis needed
- Fixed a Phase 2a bug: alerts that arrived while a client was offline were marked as handled and never sent. They are now delivered on reconnect (verified)
- Docker images: the API image (Python 3.14, non-root, optional baked Piper voices, healthcheck) and the web image (unprivileged nginx proxying API, SSE and WebSocket traffic, with security headers). Docker Compose runs Postgres, the worker, 2 API replicas and the web front
- Kubernetes (kustomize): the API with HPA 2–10, PDB, zero-downtime rolling updates and startup/readiness/liveness probes (`/api/ready` checks the database); a singleton worker; web; Postgres StatefulSet; TLS ingress tuned for WebSockets and streaming; restricted security contexts throughout
- CI: tests and frontend build on every push; images built and pushed to GHCR from `main`
- Load test (`backend/loadtest`): multi-process generator with p50/p95/p99, throughput and WebSocket hold. One API process: 525 req/s at p95 148 ms with 200 live sockets and 0 errors. It saturates at about 500 req/s without errors
- Performance fixes found by the load test: cached knowledge and voice stats (8 ms per health check before), direct JSON encoding for large replies, and a bounding-box query plus a 60 s cache for nearby observations (p50 293 ms to 63 ms). httptools on every platform, uvloop on Linux

Deferred: PostGIS alert polygons (SACHET CAP areas are matched by district name today).

## Phase 3 — Mobile app and rural voice (in progress, 2026-09-27)

Phase 3a done:
- Android app with Capacitor 8 (`in.weathergpt.app`). The same React app runs in a native shell, with the Disha compass as the adaptive launcher icon and splash screen, a dark status bar, edge-to-edge safe areas, and location, microphone and notification permissions
- The Android back button closes the search, profile and chat panels in turn, then minimises the app instead of quitting
- Push notifications through Firebase Cloud Messaging HTTP v1. The worker signs its own OAuth assertion with the service account (RS256, no Firebase SDK on the server). It pushes a new IMD/NDMA warning only to phones whose saved places match, at high priority for Severe/Extreme, with a TTL until the warning expires. Re-issued duplicates are collapsed and tokens of uninstalled apps are dropped. Verified on a real phone with the app process killed
- While the app is open, live WebSocket alerts become native notifications on a "Weather warnings" channel. Tapping any notification opens that place and asks the assistant what to do about the warning. Verified on the phone
- Notification permission is requested after the first forecast loads. Android shows one permission dialog at a time, so asking together with location dropped the request
- `npm run android` / `npm run android:run` builds the web app for the device, syncs, builds the APK and, with a phone on USB, installs and launches it. The API is reached through `adb reverse`. Push switches on automatically when `android/app/google-services.json` exists
- API: `POST /api/devices`, `POST /api/devices/unregister`, `POST /api/devices/test`; push status in `/api/system/status`
- Field note: on the campus WPA2-Enterprise Wi-Fi, FCM token registration failed with `SERVICE_NOT_AVAILABLE`, but it succeeded at once on mobile data. Register the demo phone on mobile data; the token persists

Phase 3b done:
- Speech recognition on our own server for all 12 Indian languages in the app (hi, bn, te, ta, mr, gu, kn, ml, or, pa, as, ur). It uses AI4Bharat's IndicConformer 600M multilingual, reusing iTantra's pure-ONNX export (preprocessor, int8 encoder, CTC decoder, per-language vocabulary masks). No PyTorch and no cloud
- English runs through Groq's Whisper large-v3-turbo first and falls back to a local Whisper base.en. Indian languages run locally first and fall back to Groq. `STT_ENGINE=auto|local|cloud`
- Measured on iTantra's real recordings: Hindi 0.0% WER, English 10.7% WER (local), about 0.1x real time on a laptop CPU. A phone's 5 s WebM/Opus recording is transcribed in about 0.6 s. Verified on a real phone through the Android app
- Spoken language comes from the app's language menu. Automatic detection was tested and dropped: Whisper tiny got 14/19 and base 10/19 right on short clips, and IndicConformer writes any speech faithfully in any script, so its confidence cannot identify the language
- Voice replies are sent as Ogg/Opus at 24 kbps when the device can play it (Android WebView and Chrome can). A Hindi sentence went from 176 KB WAV to 12 KB. Devices without Opus still get WAV
- Recordings are decoded with PyAV (bundled ffmpeg), so the server needs no system ffmpeg
- `scripts/fetch_stt_models.py` installs the models: Whisper base.en is downloaded from the sherpa-onnx releases, and the IndicConformer bundle is copied from an iTantra export because AI4Bharat's model is gated
- Tests: Opus encoding and decoding, and Hindi and Telugu round trips (Piper speaks, IndicConformer transcribes)

Phase 3c, part 1 done (smart notifications):
- The worker checks every saved place every 10 minutes:
  - rain starting within 2 hours (Open-Meteo 15-minute nowcast, with minutes to start and intensity);
  - thunderstorms;
  - heavy rain at IMD thresholds;
  - heat when the feels-like temperature peaks (sent in the morning);
  - gusts of 50+ km/h;
  - dense fog (sent the evening before);
  - a morning briefing at each user's chosen time.
- Official IMD/NDMA warnings go through the same pipeline and can't be switched off.
- The text is written by the LLM chain from real facts only. It is fully in the user's chat language and includes one action suited to their role and crops. English templates are the fallback.
- Behaviour:
  - quiet hours (Severe and Extreme warnings still come through);
  - at most 6 non-urgent notifications a day;
  - deduplication;
  - several hazards for one place are merged into one notification.
- "Now" comes from the weather service's own clock, not the server's.
- Delivery:
  - data-only FCM push rendered natively on four Android channels (warnings, nowcast, alerts, briefing), with "Ask WeatherGPT" and "Radar" action buttons;
  - live WebSocket;
  - a stored history.
- The bell is a notification centre with tabs, unread state, and Ask / Radar / Go to place actions. The profile has per-type toggles, the briefing time, quiet hours, and a "send me a briefing now" test.
- API: `PUT /api/notifications/prefs`, `GET /api/notifications`, `POST /api/notifications/read`, `POST /api/notifications/test`.

Phase 3c, part 2 done (low bandwidth and offline):
- The API gzips JSON: a forecast goes from 23.3 KB to 2.9 KB. Audio and event streams are left alone.
- Data saver (Automatic / Always on / Off):
  - Automatic follows the browser's effective connection type (2G or slow 3G) or the phone's data-saver flag. The raw downlink estimate was too noisy (Chrome reported "4g" at 0.15 Mbps), so it isn't used.
  - Lite mode slows the sky animation, holds the radar behind "Load live radar", and refreshes every 20 minutes. Voice is already Opus.
- Offline cache for the last forecast, warnings and insights of each place, plus the notification inbox:
  - A banner distinguishes being offline from the server being unreachable.
  - The HUD says "SAVED 12 MIN AGO" instead of LIVE.
  - Chat answers offline from the saved forecast.
  - Everything recovers by itself when the connection comes back.
- A service worker keeps the web app shell and fonts available offline (production web builds only; the Android app bundles its assets).
- Fixed: IMD BUFR decoding ran on the event loop and stalled requests for up to 43 s after startup. It now runs in a worker thread.

Trip planner (new tab next to Weather; the existing weather view is unchanged and the same WeatherGPT chat stays on the right):
- Real routes:
  - OSRM on OpenStreetMap for car, two-wheeler and bus, with up to 3 alternatives. Per-segment durations come from OSRM annotations; bus is about 30% and two-wheeler about 12% slower than car.
  - OSRM foot routing for treks.
  - Great-circle routing between the nearest scheduled airports (116 Indian airports from OurAirports), with live METAR/TAF and a 250 hPa tail/headwind estimate for flights.
  - Indian railway lines from OpenStreetMap for trains, routed with A* between the nearest stations. The graph is built by `scripts/build_rail_graph.py` from the Geofabrik India extract (1.7 GB) using pyosmium in about 45 s. Station tracks tagged as sidings or yards are kept so big terminals stay connected; only industrial spurs and freight, military or test lines are dropped, and only the main connected network is used. The result is 122,040 km of track, 125,840 junction and station nodes and 8,785 stations, and routes prefer Junction, Central, Terminus and City stations. Checked: Delhi → Chennai is 2,176 km via Jhansi, Itarsi and Warora, close to the 2,182 km of the Tamil Nadu Express; Mumbai LTT → Howrah is 1,946 km. Train time is estimated at 52 km/h for short trips and 62 km/h for long ones.
- Weather comes from Open-Meteo at up to 32 checkpoints, each read for the hour the traveller reaches it (parallel batches).
- Each checkpoint is rated for thunderstorm, rain, fog, wind, heat, cold and snow with mode-specific thresholds. Two-wheelers and treks are more exposed; trains are only really affected by fog and storms; flights are rated for convection and the jet stream at cruise.
- Consecutive hazards merge into spans with the nearest real town and mode-specific advice. Official IMD/NDMA warnings are listed only for districts the route passes through.
- The best departure time is searched over the next 12 hours, and night travel is flagged.
- The map colours the route by risk at the time of passage, shows grey alternatives you can tap, and has checkpoint tooltips and a RainViewer radar overlay. The view also has a risk strip, departure bars, hazards, airports or stations, and a timeline. The last trip is kept offline.
- Chat integration:
  - A `plan_trip` agent tool lets you plan a trip by chatting; it produces a trip card with "Open in trip planner".
  - The open trip's briefing is sent as context so answers stay about that trip.
  - search_knowledge is prompted for official hazard guidance.
- Tests cover great-circle maths, sampling, mode-specific hazard levels, span merging, rail A* and arrival-hour lookup.

SMS and IVR for feature phones (Phase 3c, part 3, 2026-09-28):
- The phone layer doesn't depend on one provider. It runs in simulator mode until a telecom account is connected, and a Twilio adapter is included:
  - REST for SMS and calls;
  - TwiML for the voice menu;
  - every webhook checks the X-Twilio-Signature (HMAC-SHA1) against `PUBLIC_BASE_URL`.
  - In India, real SMS also needs DLT registration of the sender ID and templates.
- SMS commands work in English, Hindi and Indic scripts:
  - `WEATHER <PIN or village>` returns today's forecast;
  - `JOIN <place>` subscribes to warnings and a 06:30 briefing;
  - `LANG <code or name>` changes the language;
  - `STOP` and `HELP`;
  - any other text is a question answered by the WeatherGPT agent.
  - PIN codes are resolved with the India Post API and matched to a geocoded place in the same state.
- Replies are written in the subscriber's language and trimmed at sentence boundaries to at most 3 SMS. Segments are counted by GSM-7 / UCS-2 rules.
- Translation has safeguards:
  - A translation is rejected if it is a refusal, loses or changes a number or placeholder, is not mainly in the target script, or is too short.
  - After two failed attempts the English text is used.
  - Menus are translated sentence by sentence, and place names are filled in after translation.
- Voice helpline (IVR) flow:
  1. A language menu is spoken in each language's own voice.
  2. The caller keys in a 6-digit PIN code.
  3. The main menu: 1 today's weather, 2 official warnings, 3 farm advice (spray window and irrigation), 4 join warnings on this phone, 5 change place, 9 language.
  - Prompts are local Piper TTS concatenated into 16 kHz WAV and cached.
  - Silence is handled: the prompt repeats, and the call hangs up after three misses.
- Automatic delivery:
  - New IMD/NDMA warnings that match a subscriber's district go out by SMS, in the language the issuer published if available, otherwise translated.
  - Severe and Extreme warnings also place a voice call that reads the warning and offers 1 repeat, 2 today's weather, 8 stop calls.
  - Everything is deduplicated per warning text.
  - The worker's `phone` job sends the morning briefings.
- A family member can add a parent's keypad phone from the profile ("Basic phones in the family"). The parent gets an SMS and joins by replying YES. Numbers are masked in the app and removed by an opaque reference.
- The keypad phone simulator at `/phone` has:
  - an SMS thread;
  - a green/red call key and keypad with real DTMF tones driving the IVR, with prompts played as audio;
  - incoming warning calls with Answer/Reject;
  - a clearly labelled "practice warning" drill (simulator mode only).
- API endpoints:
  - `POST /api/phone/sim/sms`, `GET /api/phone/sim/thread`, `POST /api/phone/sim/call`, `POST /api/phone/sim/drill`
  - `GET /api/ivr/audio/{key}.wav`
  - `POST|GET /api/phone/family`, `POST /api/phone/family/remove`
  - `POST /api/sms/twilio`, `POST /api/ivr/twilio`
  - `GET /api/phone/status`

Still in Phase 3:
- Connect a real SMS/voice provider (needs an account and DLT registration)
- 24/7 hosting (deferred on 2026-09-27). Until then the backend runs on the laptop, so automatic notifications stop when it sleeps.
  - The Oracle Cloud Always Free signup (Ampere A1, Hyderabad) failed Oracle's risk check, and a support case is open.
  - Plan once a VM exists:
    - Docker Compose with Caddy HTTPS on an sslip.io address;
    - copy `.env`, `secrets/` and the models;
    - rebuild the app with `--api https://...`;
    - upgrade the account to Pay As You Go so idle free VMs aren't reclaimed.
  - Fallback: $200 DigitalOcean credit from the GitHub Student Pack.

## Phase 4 — Maps and GIS

- Radar/satellite and model field layers (rain, wind, temperature) on a map
- Cyclone track visualisation; district-level warning map

## Phase 5 — Evaluation

- Accuracy: forecast verification against observations; answer grounding checks
- Latency: measured p50/p95 for first token and full answer
- Multilingual quality review with native speakers
