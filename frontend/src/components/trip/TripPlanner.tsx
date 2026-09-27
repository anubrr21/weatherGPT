import { ArrowDownUp, Bike, Bus, Car, Clock, Coffee, Footprints, Loader2, MessageSquareText, Moon, Plane, ShieldAlert, TrainFront } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { savedAgo } from '../../lib/offline'
import {
  HAZARD_LABELS,
  MODES,
  REST_MODES,
  clock,
  dayClock,
  duration,
  levelColor,
  loadLastTrip,
  localInputValue,
  planTrip,
  saveLastTrip,
  type TripMode,
  type TripResult,
} from '../../lib/trip'
import type { Place } from '../../lib/types'
import PlaceInput from './PlaceInput'
import RestStops from './RestStops'
import TripMap from './TripMap'

const ICONS: Record<TripMode, typeof Car> = { car: Car, bike: Bike, bus: Bus, train: TrainFront, flight: Plane, trek: Footprints }
const STEPS = ['Finding the real route…', 'Reading the forecast at each point for when you will be there…', 'Checking official IMD and NDMA warnings along the way…', 'Comparing departure times…']

interface Props {
  current: Place | null
  online: boolean
  lite: boolean
  incoming: TripResult | null
  onTrip: (brief: Record<string, unknown> | null) => void
  onAsk: (text: string) => void
}

export default function TripPlanner({ current, online, lite, incoming, onTrip, onAsk }: Props) {
  const saved = useMemo(loadLastTrip, [])
  const [from, setFrom] = useState<Place | null>(saved?.result.origin ?? current)
  const [to, setTo] = useState<Place | null>(saved?.result.destination ?? null)
  const [mode, setMode] = useState<TripMode>(saved?.result.mode ?? 'car')
  const [leaveNow, setLeaveNow] = useState(true)
  const [restStops, setRestStops] = useState(() => Boolean(saved?.result.routes.some((r) => r.rest_stops)))
  const [when, setWhen] = useState(() => localInputValue(new Date(Date.now() + 3600 * 1000)))
  const [trip, setTrip] = useState<TripResult | null>(saved?.result ?? null)
  const [savedAt, setSavedAt] = useState<number | null>(saved?.savedAt ?? null)
  const [selected, setSelected] = useState(0)
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!incoming) return
    setTrip(incoming)
    setFrom(incoming.origin)
    setTo(incoming.destination)
    setMode(incoming.mode)
    setSelected(0)
    setSavedAt(null)
    saveLastTrip(incoming)
  }, [incoming])

  useEffect(() => {
    onTrip(trip ? (trip.briefs?.[selected] ?? null) : null)
  }, [trip, selected])

  useEffect(() => {
    if (!busy) return
    const id = setInterval(() => setStep((s) => Math.min(STEPS.length - 1, s + 1)), 2600)
    return () => clearInterval(id)
  }, [busy])

  const plan = async () => {
    if (!from || !to) return
    setBusy(true)
    setStep(0)
    setError(null)
    try {
      const depart = leaveNow ? null : `${when}:00+05:30`
      const result = await planTrip(from, to, mode, depart, restStops && REST_MODES.includes(mode))
      setTrip(result)
      setSelected(0)
      setSavedAt(null)
      saveLastTrip(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const route = trip?.routes[selected]
  const worstDeparture = route ? Math.max(1, ...route.departures.map((d) => d.score)) : 1

  return (
    <div className="trip">
      <header className="trip-head">
        <h1>Trip planner</h1>
        <p>Weather along your real route, at the time you will be at each point.</p>
      </header>

      <section className="trip-form">
        <div className="trip-places">
          <PlaceInput label="From" value={from} onChange={setFrom} current={current} />
          <button
            className="icon-btn trip-swap"
            aria-label="Swap start and destination"
            onClick={() => {
              setFrom(to)
              setTo(from)
            }}
          >
            <ArrowDownUp size={16} />
          </button>
          <PlaceInput label="To" value={to} onChange={setTo} autoFocus={!to} />
        </div>
        <div className="trip-modes" role="radiogroup" aria-label="How are you travelling?">
          {MODES.map((m) => {
            const Icon = ICONS[m.id]
            return (
              <button key={m.id} role="radio" aria-checked={mode === m.id} className={mode === m.id ? 'on' : ''} onClick={() => setMode(m.id)}>
                <Icon size={16} />
                <span>{m.label}</span>
              </button>
            )
          })}
        </div>
        <div className="trip-when">
          <label className="switch">
            <input type="checkbox" checked={leaveNow} onChange={(e) => setLeaveNow(e.target.checked)} />
            <span>Leave now</span>
          </label>
          {REST_MODES.includes(mode) && (
            <label className="switch">
              <input type="checkbox" checked={restStops} onChange={(e) => setRestStops(e.target.checked)} />
              <span>Plan rest stops</span>
            </label>
          )}
          {!leaveNow && (
            <input
              type="datetime-local"
              value={when}
              min={localInputValue(new Date())}
              max={localInputValue(new Date(Date.now() + 6 * 86400 * 1000))}
              onChange={(e) => setWhen(e.target.value)}
              aria-label="Departure time"
            />
          )}
          <button className="trip-go" disabled={!from || !to || busy || !online} onClick={plan}>
            {busy ? <Loader2 size={16} className="spin" /> : null}
            {busy ? 'Planning…' : online ? 'Plan trip' : 'Offline'}
          </button>
        </div>
        {busy && <p className="trip-step">{STEPS[step]}</p>}
        {error && <p className="trip-error">{error}</p>}
      </section>

      {trip && route && (
        <>
          {savedAt && (
            <p className="trip-saved">
              Showing your last trip, planned {savedAgo(savedAt)}. {online ? 'Plan again for fresh weather.' : 'You are offline.'}
            </p>
          )}

          <section className="trip-summary">
            <div className="trip-route-title">
              <span>
                <b>
                  {trip.origin.name} → {trip.destination.name}
                </b>
                <small>
                  {trip.mode_label} · {route.summary}
                </small>
              </span>
              <em className={`trip-risk r${Math.min(3, Math.floor(route.risk.score))}`}>{route.risk.label} risk</em>
            </div>
            <div className="trip-stats">
              <span>
                <small>Distance</small>
                <b>{route.distance_km.toLocaleString('en-IN')} km</b>
              </span>
              <span>
                <small>Travel time</small>
                <b>{duration(route.duration_min)}</b>
              </span>
              <span>
                <small>Leave</small>
                <b>{dayClock(route.depart)}</b>
              </span>
              <span>
                <small>Arrive</small>
                <b>{dayClock(route.arrive)}</b>
              </span>
            </div>
            {route.night_share >= 0.4 && trip.mode !== 'flight' && trip.mode !== 'train' && (
              <p className="trip-note">
                <Moon size={14} /> About {Math.round(route.night_share * 100)}% of this trip is after dark. Plan rest stops and keep headlights clean.
              </p>
            )}
            <div className="trip-strip" aria-label="Weather risk along the route">
              {route.points.slice(0, -1).map((p, k) => {
                const next = route.points[k + 1]
                return <i key={p.i} style={{ flex: Math.max(0.5, next.km - p.km), background: levelColor(Math.max(p.level, next.level)) }} title={`${p.km}–${next.km} km · ${clock(p.eta)}`} />
              })}
            </div>
            <div className="trip-strip-labels">
              <span>{clock(route.depart)} · {trip.origin.name}</span>
              <span>{trip.destination.name} · {clock(route.arrive)}</span>
            </div>
          </section>

          {trip.routes.length > 1 && (
            <nav className="trip-alts" aria-label="Route options">
              {trip.routes.map((r, i) => (
                <button key={i} className={i === selected ? 'on' : ''} onClick={() => setSelected(i)}>
                  <b>{r.summary}</b>
                  <small>
                    {duration(r.duration_min)} · {Math.round(r.distance_km)} km · <em style={{ color: levelColor(r.risk.score) }}>{r.risk.label}</em>
                  </small>
                </button>
              ))}
            </nav>
          )}

          <TripMap trip={trip} selected={selected} onSelect={setSelected} lite={lite} />

          {route.departures.length > 1 && (
            <section className="trip-card">
              <h3>
                <Clock size={15} /> Best time to leave
              </h3>
              <div className="trip-bars">
                {route.departures.map((d) => (
                  <span key={d.depart} title={`${clock(d.depart)} · ${d.risk} risk`} className={route.best_departure?.depart === d.depart ? 'best' : ''}>
                    <i style={{ height: `${18 + (d.score / worstDeparture) * 62}%`, background: levelColor(d.score) }} />
                    <small>{clock(d.depart).slice(0, 2)}</small>
                  </span>
                ))}
              </div>
              <p>
                {route.best_departure
                  ? `Leave at ${clock(route.best_departure.depart)} instead. ${route.best_departure.why}.`
                  : `Your planned time is already as good as it gets in the next 12 hours (${route.risk.label.toLowerCase()} risk).`}
              </p>
            </section>
          )}

          <section className="trip-card">
            <h3>
              <ShieldAlert size={15} /> Along the way
            </h3>
            {route.hazards.length === 0 && route.alerts.length === 0 ? (
              <p className="trip-clear">No weather hazards expected along this route at your travel time.</p>
            ) : (
              <ul className="trip-hazards">
                {route.alerts.map((a) => (
                  <li key={a.id} className="official">
                    <em>IMD / NDMA · {a.severity}</em>
                    <b>
                      {a.event ?? 'Official warning'}
                      {a.near ? ` near ${a.near}` : ''}
                      {a.km !== undefined ? ` (km ${a.km})` : ''}
                    </b>
                    <small>{a.headline}</small>
                  </li>
                ))}
                {route.hazards.map((h, k) => (
                  <li key={k} style={{ borderLeftColor: levelColor(h.level) }}>
                    <em>
                      {h.severity} · {HAZARD_LABELS[h.kind] ?? h.kind}
                    </em>
                    <b>
                      {h.detail}
                      {h.near ? ` near ${h.near}` : ''}
                    </b>
                    <small>
                      km {Math.round(h.from_km)}–{Math.round(h.to_km)} · {clock(h.from_eta)}–{clock(h.to_eta)}. {h.advice}
                    </small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {trip.routes.some((r) => r.rest_stops) && (
            <section className="trip-card">
              <h3>
                <Coffee size={15} /> Rest stops
              </h3>
              {route.rest_stops ? (
                <RestStops stops={route.rest_stops} mode={trip.mode} />
              ) : (
                <p className="rest-none">
                  Rest stops are planned on {trip.routes.find((r) => r.rest_stops)?.summary ?? 'the main route'}. Switch to it to see them.
                </p>
              )}
              <p className="trip-source">
                Breaks every {trip.mode === 'bike' ? '1.5' : '2'} hours of {trip.mode === 'bike' ? 'riding' : 'driving'}, plus an overnight stop for very long or late-night drives. Times do not include
                the breaks themselves. Places from OpenStreetMap; check they are open before relying on them.
              </p>
            </section>
          )}

          {(route.extra.from_airport || route.extra.from_station) && (
            <section className="trip-card">
              <h3>
                {route.extra.from_airport ? <Plane size={15} /> : <TrainFront size={15} />} {route.extra.from_airport ? 'Airports' : 'Stations'}
              </h3>
              <ul className="trip-ends">
                {route.extra.from_airport &&
                  [route.extra.from_airport, route.extra.to_airport].map((airport, k) =>
                    airport ? (
                      <li key={airport.icao}>
                        <b>
                          {k ? 'Arrive' : 'Depart'} · {airport.name} ({airport.iata ?? airport.icao})
                        </b>
                        <small>{k ? `${airport.km_from_destination ?? 0} km from ${trip.destination.name}` : `${airport.km_from_origin ?? 0} km from ${trip.origin.name}`}</small>
                        {airport.metar?.raw_metar && <code>{airport.metar.raw_metar}</code>}
                        {airport.metar?.raw_taf && <code className="taf">{airport.metar.raw_taf}</code>}
                      </li>
                    ) : null,
                  )}
                {!route.extra.from_airport &&
                  [route.extra.from_station, route.extra.to_station].map((station, k) =>
                    station ? (
                      <li key={`${station.name}-${k}`}>
                        <b>
                          {k ? 'Arrive' : 'Depart'} · {station.name}
                        </b>
                        <small>{k ? `${station.km_from_destination ?? 0} km from ${trip.destination.name}` : `${station.km_from_origin ?? 0} km from ${trip.origin.name}`}</small>
                      </li>
                    ) : null,
                  )}
              </ul>
              {route.extra.winds && (
                <p>
                  Jet-level wind gives a {route.extra.winds.tailwind_kmh >= 0 ? 'tailwind' : 'headwind'} of about {Math.abs(route.extra.winds.tailwind_kmh)} km/h, so
                  gate to gate is roughly {duration(route.extra.winds.adjusted_minutes)}.
                </p>
              )}
            </section>
          )}

          <section className="trip-card">
            <h3>Checkpoints</h3>
            <ol className="trip-timeline">
              {route.points
                .filter((p, k) => k === 0 || k === route.points.length - 1 || p.place || p.level >= 1)
                .map((p) => (
                  <li key={p.i}>
                    <time>{clock(p.eta)}</time>
                    <i style={{ background: levelColor(p.level) }} />
                    <span>
                      <b>{p.place ?? `${p.km} km`}</b>
                      <small>
                        {p.weather
                          ? `${p.weather.label} · ${p.weather.temp !== null ? Math.round(p.weather.temp) : '–'}°C` +
                            (p.weather.rain_prob !== null ? ` · rain ${p.weather.rain_prob}%` : '') +
                            (p.weather.gust ? ` · gusts ${Math.round(p.weather.gust)} km/h` : '')
                          : 'Beyond the forecast range'}
                      </small>
                    </span>
                    <em>{p.km} km</em>
                  </li>
                ))}
            </ol>
          </section>

          <button
            className="trip-ask"
            onClick={() =>
              onAsk(`I'm planning this ${trip.mode_label.toLowerCase()} trip from ${trip.origin.name} to ${trip.destination.name}, leaving ${dayClock(route.depart)}. How is the weather along the way, what should I watch out for and what should I carry?`)
            }
          >
            <MessageSquareText size={16} /> Ask WeatherGPT about this trip
          </button>

          <p className="trip-source">
            Route: {route.source}. Weather: Open-Meteo forecast at each checkpoint for the hour you reach it. Warnings: IMD and NDMA via SACHET.
          </p>
        </>
      )}
    </div>
  )
}
