import { Anchor, CalendarDays, LifeBuoy, Loader2, MessageSquareText, Moon, Phone, RefreshCw, Sunrise, Waves, Wind } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { dayName, workApi, type Boat, type SeaVerdict, type SeaWorkspace } from '../../lib/work'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const BOAT_KEY = 'weathergpt:boat'
const COLORS: Record<SeaVerdict, string> = { GO: '#5fd39a', CAUTION: '#ffc857', 'NO-GO': '#ff4d6d' }
const WORDS: Record<SeaVerdict, string> = { GO: 'Safe to go', CAUTION: 'Go with caution', 'NO-GO': 'Do not go' }
const clock = (iso: string | null) => (iso ? iso.slice(11, 16) : '–')

function savedBoat(): Boat {
  try {
    const value = localStorage.getItem(BOAT_KEY)
    return value === 'small' || value === 'trawler' ? value : 'motor'
  } catch {
    return 'motor'
  }
}

function TideChart({ hours }: { hours: SeaWorkspace['hours'] }) {
  const points = hours.filter((h) => h.tide !== null)
  if (points.length < 6) return null
  const width = 600
  const height = 90
  const values = points.map((p) => p.tide as number)
  const low = Math.min(...values)
  const high = Math.max(...values)
  const x = (k: number) => (k / (points.length - 1)) * width
  const y = (v: number) => height - ((v - low) / (high - low || 1)) * (height - 12) - 6
  const line = points.map((p, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(p.tide as number).toFixed(1)}`).join(' ')
  return (
    <svg className="sea-tide" viewBox={`0 0 ${width} ${height + 16}`} preserveAspectRatio="none" role="img" aria-label="Tide height for the next three days">
      <path d={`${line} L${width},${height} L0,${height} Z`} className="sea-tide-fill" />
      <path d={line} className="sea-tide-line" />
      {points.map((p, k) =>
        p.time.endsWith('T00:00') ? (
          <g key={p.time}>
            <line x1={x(k)} x2={x(k)} y1="0" y2={height} className="cy-chart-rule" />
            <text x={x(k) + 3} y={height + 13} className="cy-chart-day">
              {new Date(`${p.time}:00`).toLocaleDateString('en-IN', { weekday: 'short' })}
            </text>
          </g>
        ) : null,
      )}
    </svg>
  )
}

export default function SeaView({ place, online, onAsk }: Props) {
  const [data, setData] = useState<SeaWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [boat, setBoatState] = useState<Boat>(savedBoat)

  const setBoat = (next: Boat) => {
    setBoatState(next)
    try {
      localStorage.setItem(BOAT_KEY, next)
    } catch {
      return
    }
  }

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache('sea', place.lat, place.lon, () => workApi.sea(place.lat, place.lon), online)
      setData(result.data)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, online])

  useEffect(() => {
    load()
  }, [load])

  if (!place) return <div className="cy"><p className="trip-step">Pick a coastal place to see the sea.</p></div>

  const ready = data?.available && Array.isArray(data.days) ? data : null
  const now = ready?.now
  const verdictNow = now?.verdicts[boat]
  const limits = ready?.boats[boat]

  return (
    <div className="cy sea">
      <header className="trip-head cy-head">
        <h1>Your sea</h1>
        <p>Waves, wind, tides and a go or no-go for your boat off {place.name}, for the next five days.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh sea conditions">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {loading && !data && <p className="trip-step">Reading the sea forecast…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {data && !data.available && <p className="trip-error">{data.reason}</p>}
      {savedAt && <p className="trip-saved">Showing sea conditions saved {savedAgo(savedAt)}. The sea changes fast, so check again before leaving.</p>}

      {ready && (
        <div className="chips" role="radiogroup" aria-label="Your boat">
          {(Object.keys(ready.boats) as Boat[]).map((b) => (
            <button key={b} role="radio" aria-checked={boat === b} className={boat === b ? 'on' : ''} onClick={() => setBoat(b)}>
              {ready.boats[b].label}
            </button>
          ))}
        </div>
      )}

      {ready && ready.official.length > 0 && (
        <section className="cy-official">
          {ready.official.map((a, k) => (
            <article key={k}>
              <em>Official · {a.severity}</em>
              <b>{a.event ?? 'Sea warning'}</b>
              <p>{a.headline}</p>
            </article>
          ))}
        </section>
      )}

      {ready && now && verdictNow && (
        <section className="sea-hero" style={{ borderColor: COLORS[verdictNow] }}>
          <b style={{ color: COLORS[verdictNow] }}>{WORDS[verdictNow]}</b>
          <p>
            {ready.official.length
              ? 'An official sea warning is in force for this coast.'
              : now.reasons[boat].length
                ? `Right now: ${now.reasons[boat].join(', ')}.`
                : `Right now the sea is within safe limits for a ${ready.boats[boat].label.toLowerCase()}.`}
            {limits ? ` Limits for this boat: caution from ${limits.caution[0]} m waves or ${limits.caution[1]} km/h gusts, do not go from ${limits.nogo[0]} m or ${limits.nogo[1]} km/h.` : ''}
          </p>
        </section>
      )}

      {ready && now && (
        <div className="cy-stats">
          <span>
            <small>
              <Waves size={11} /> Waves
            </small>
            <b>{now.wave ?? '–'} m</b>
            <em>
              from {now.wave_dir ?? '–'} · every {now.wave_period ? Math.round(now.wave_period) : '–'} s
            </em>
          </span>
          <span>
            <small>Swell</small>
            <b>{now.swell ?? '–'} m</b>
            <em>
              from {now.swell_dir ?? '–'} · {now.swell_period ? Math.round(now.swell_period) : '–'} s
            </em>
          </span>
          <span>
            <small>
              <Wind size={11} /> Wind
            </small>
            <b>{now.wind !== null ? Math.round(now.wind) : '–'} km/h</b>
            <em>
              from {now.wind_dir ?? '–'} · gusts {now.gust !== null ? Math.round(now.gust) : '–'}
            </em>
          </span>
          <span>
            <small>Current</small>
            <b>{now.current_kmh ?? '–'} km/h</b>
            <em>towards {now.current_dir ?? '–'}</em>
          </span>
          <span>
            <small>Sea temperature</small>
            <b>{now.sst ?? '–'} °C</b>
          </span>
          <span>
            <small>Visibility</small>
            <b>{now.visibility !== null ? `${Math.round(now.visibility / 1000)} km` : '–'}</b>
          </span>
        </div>
      )}

      {ready && (
        <section className="trip-card">
          <h3>
            <CalendarDays size={15} /> Next five days for a {ready.boats[boat].label.toLowerCase()}
          </h3>
          <ul className="sea-days">
            {ready.days.map((d) => {
              const b = d.boats[boat]
              return (
                <li key={d.date}>
                  <em style={{ background: COLORS[b.verdict] }}>{b.verdict}</em>
                  <span>
                    <b>{dayName(d.date, ready.generated.slice(0, 10))}</b>
                    <small>
                      waves to {d.wave_max.toFixed(1)} m · gusts to {d.gust_max} km/h{d.thunder ? ' · thunderstorms' : ''}
                      {d.rain_mm >= 1 ? ` · ${d.rain_mm} mm rain` : ''}
                    </small>
                    <small>
                      {b.windows.some((w) => w.hours >= 23)
                        ? 'Calm all day'
                        : b.windows.length
                        ? `Calm hours: ${b.windows.map((w) => `${clock(w.start)}–${clock(w.end)}`).join(', ')}`
                        : b.verdict === 'GO'
                          ? 'Calm all day'
                          : 'No calm stretch of 3 hours'}
                    </small>
                  </span>
                  <span className="sea-sun">
                    <Sunrise size={12} /> {clock(d.sunrise)}–{clock(d.sunset)}
                  </span>
                </li>
              )
            })}
          </ul>
          <h4 className="trip-sub">Hour by hour, next 3 days</h4>
          <div className="sea-hours">
            {ready.hours.map((h) => (
              <span key={h.time} title={`${h.time.replace('T', ' ')} · waves ${h.wave} m · gusts ${h.gust !== null ? Math.round(h.gust) : '–'} km/h${h.thunder ? ' · thunder' : ''}`}>
                <i style={{ height: `${Math.min(100, ((h.wave ?? 0) / 3) * 100)}%`, background: COLORS[h.verdicts[boat]] }} />
                {h.time.endsWith('T00:00') && <small>{new Date(`${h.time}:00`).toLocaleDateString('en-IN', { weekday: 'short' })}</small>}
              </span>
            ))}
          </div>
          <p className="trip-source">Bar height is wave height (full height = 3 m); colour is the verdict for your boat. {ready.rules}</p>
        </section>
      )}

      {ready && (
        <section className="trip-card">
          <h3>
            <Anchor size={15} /> Tides
          </h3>
          <div className="sea-tides">
            {ready.next_tides.map((t) => (
              <span key={t.time} className={t.type}>
                <small>{t.type === 'high' ? 'High tide' : 'Low tide'}</small>
                <b>{clock(t.time)}</b>
                <em>
                  {dayName(t.time.slice(0, 10), ready.generated.slice(0, 10))} · {t.height_m.toFixed(2)} m
                </em>
              </span>
            ))}
          </div>
          <TideChart hours={ready.hours} />
          <p>
            <Moon size={13} /> {ready.moon.phase}, {ready.moon.illumination}% lit.{' '}
            {ready.moon.spring_tide ? 'Near new or full moon: spring tides, so highs are higher, lows are lower and currents at river mouths are stronger.' : 'Tides are in their ordinary range.'}
          </p>
          <p className="trip-source">Heights are sea level against mean sea level from the ocean model, so use them for timing; harbour tide tables can differ.</p>
        </section>
      )}

      <section className="trip-card">
        <h3>
          <LifeBuoy size={15} /> Before you leave shore
        </h3>
        <ul className="sea-check">
          <li>Life jackets for everyone on board, worn, not stowed.</li>
          <li>Tell your family or society where you are going and when you will return.</li>
          <li>Carry a charged phone in a waterproof cover, your distress alert transmitter or radio, and extra fuel and water.</li>
          <li>Turn back at the first sign of thunder, rising wind or swell.</li>
          <li>Never cross an official fishermen warning or the port's storm signal.</li>
        </ul>
        <div className="cy-helplines">
          <a href="tel:1554">
            <Phone size={13} /> <b>1554</b> Coast Guard search and rescue
          </a>
          <a href="tel:112">
            <Phone size={13} /> <b>112</b> Emergency
          </a>
        </div>
      </section>

      <button className="trip-ask" onClick={() => onAsk(`Can I take my ${ready ? ready.boats[boat].label.toLowerCase() : 'boat'} out from ${place.name} today and tomorrow? What are the waves, wind and tides, and when is the safest time?`)}>
        <MessageSquareText size={16} /> Ask WeatherGPT about the sea
      </button>
      {ready && <p className="trip-source">{ready.source}.</p>}
    </div>
  )
}
