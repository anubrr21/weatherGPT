import { Bike, Bus, CloudRain, Loader2, MessageSquareText, RefreshCw, Sun, ThermometerSun, Waves, Wind } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { dayName, workApi, type CityWorkspace } from '../../lib/work'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const COMMUTE_KEY = 'weathergpt:commute'
const HEAT_COLORS: Record<string, string> = { comfortable: '#5fd39a', caution: '#ffd166', 'extreme caution': '#ff9f43', danger: '#ff4d6d', 'extreme danger': '#b42bd6' }
const AIR_COLORS: Record<string, string> = { Good: '#5fd39a', Satisfactory: '#b6e06a', Moderate: '#ffd166', Poor: '#ff9f43', 'Very poor': '#ff4d6d', Severe: '#b42bd6' }
const FLOOD_COLORS = { none: '#5fd39a', low: '#ffd166', moderate: '#ff9f43', high: '#ff4d6d' }
const FLOOD_WORDS = { none: 'No waterlogging expected', low: 'Puddles on low roads', moderate: 'Waterlogging likely in low areas', high: 'Flooded roads and underpasses likely' }
const clock = (iso: string) => iso.slice(11, 16)

const heatBand = (v: number) => (v >= 54 ? 'extreme danger' : v >= 41 ? 'danger' : v >= 32 ? 'extreme caution' : v >= 27 ? 'caution' : 'comfortable')
const airBand = (v: number | null) => (v === null ? null : v <= 30 ? 'Good' : v <= 60 ? 'Satisfactory' : v <= 90 ? 'Moderate' : v <= 120 ? 'Poor' : v <= 250 ? 'Very poor' : 'Severe')

function savedCommute(): [number, number] {
  try {
    const value = JSON.parse(localStorage.getItem(COMMUTE_KEY) ?? 'null') as [number, number] | null
    return Array.isArray(value) && value.length === 2 ? value : [9, 18]
  } catch {
    return [9, 18]
  }
}

export default function CityView({ place, online, onAsk }: Props) {
  const [data, setData] = useState<CityWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [commute, setCommuteState] = useState<[number, number]>(savedCommute)

  const setCommute = (next: [number, number]) => {
    setCommuteState(next)
    try {
      localStorage.setItem(COMMUTE_KEY, JSON.stringify(next))
    } catch {
      return
    }
  }

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache(`city-${commute[0]}-${commute[1]}`, place.lat, place.lon, () => workApi.city(place.lat, place.lon, commute[0], commute[1]), online)
      setData(Array.isArray(result.data.hours) ? result.data : null)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, commute[0], commute[1], online])

  useEffect(() => {
    load()
  }, [load])

  if (!place) return <div className="cy"><p className="trip-step">Pick your city to plan the day.</p></div>

  const now = data?.now

  return (
    <div className="cy city">
      <header className="trip-head cy-head">
        <h1>Your city day</h1>
        <p>Commute, waterlogging, heat and air for {place.name}, hour by hour for the next two days.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh city day">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {loading && !data && <p className="trip-step">Checking your commute, the heat and the air…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing the city day saved {savedAgo(savedAt)}.</p>}

      {data?.warnings && data.warnings.length > 0 && (
        <section className="cy-official">
          {data.warnings.slice(0, 2).map((w, k) => (
            <article key={k}>
              <em>IMD / NDMA · {w.severity}</em>
              <b>{w.event ?? 'Warning'}</b>
              <p>{w.headline}</p>
            </article>
          ))}
        </section>
      )}

      {now && (
        <div className="cy-stats">
          <span style={{ borderTop: `3px solid ${HEAT_COLORS[now.heat_band] ?? '#fff'}` }}>
            <small>
              <ThermometerSun size={11} /> Feels like
            </small>
            <b>{Math.round(now.heat_index)} °C</b>
            <em>{now.heat_band}</em>
          </span>
          <span style={{ borderTop: `3px solid ${AIR_COLORS[now.air_band ?? ''] ?? '#fff'}` }}>
            <small>
              <Wind size={11} /> Air quality
            </small>
            <b>{now.air_band ?? '–'}</b>
            <em>{now.naqi !== null ? `India AQI ${now.naqi}` : ''}{now.pm25 !== null ? ` · PM2.5 ${Math.round(now.pm25)}` : ''}</em>
          </span>
          <span>
            <small>
              <CloudRain size={11} /> Rain
            </small>
            <b>{now.rain_in_min !== null ? (now.rain_in_min <= 0 ? 'Raining now' : `In ${now.rain_in_min} min`) : 'None soon'}</b>
            <em>{now.rain_next_3h_mm} mm in the next 3 h</em>
          </span>
          <span>
            <small>
              <Sun size={11} /> UV now
            </small>
            <b>{now.uv !== null ? now.uv.toFixed(1) : '–'}</b>
          </span>
        </div>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <Bus size={15} /> Your commute
          </h3>
          <div className="city-times">
            <label>
              Morning at
              <select value={commute[0]} onChange={(e) => setCommute([Number(e.target.value), commute[1]])}>
                {[5, 6, 7, 8, 9, 10, 11].map((h) => (
                  <option key={h} value={h}>{`${String(h).padStart(2, '0')}:00`}</option>
                ))}
              </select>
            </label>
            <label>
              Evening at
              <select value={commute[1]} onChange={(e) => setCommute([commute[0], Number(e.target.value)])}>
                {[15, 16, 17, 18, 19, 20, 21, 22].map((h) => (
                  <option key={h} value={h}>{`${h}:00`}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="city-trips">
            {data.commute.trips.map((t) => (
              <article key={t.date + t.label} className={t.thunder || t.rain_mm >= 7.5 ? 'bad' : t.rain_mm >= 0.5 || t.rain_prob >= 50 || t.heat_index >= 41 ? 'warn' : 'good'}>
                <small>
                  {dayName(t.date, data.today)} · {t.label.toLowerCase()} {String(t.hour).padStart(2, '0')}:00
                </small>
                <b>{t.tips[0]}</b>
                {t.tips.slice(1).map((tip) => (
                  <p key={tip}>{tip}</p>
                ))}
                <em>
                  rain {t.rain_mm} mm · {t.rain_prob}% · feels {Math.round(t.heat_index)} °C
                </em>
                {t.better_time && <p className="shift">Drier at {clock(t.better_time)}.</p>}
              </article>
            ))}
          </div>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <Waves size={15} /> Waterlogging risk
          </h3>
          <ul className="city-flood">
            {data.flooding.map((f) => (
              <li key={f.date}>
                <i style={{ background: FLOOD_COLORS[f.level] }} />
                <span>
                  <b>
                    {dayName(f.date, data.today)}: {FLOOD_WORDS[f.level]}
                  </b>
                  <small>
                    {f.total_mm} mm in the day · heaviest hour {f.max_1h_mm} mm · heaviest 3 hours {f.max_3h_mm} mm{f.peak_time && f.level !== 'none' ? ` around ${clock(f.peak_time)}` : ''}
                  </small>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <ThermometerSun size={15} /> Heat stress, next 48 hours
          </h3>
          <div className="city-strip">
            {data.hours.map((h) => (
              <span key={h.time} title={`${h.time.replace('T', ' ')} · feels ${Math.round(h.heat_index)} °C`}>
                <i style={{ background: HEAT_COLORS[heatBand(h.heat_index)], height: `${Math.min(100, Math.max(15, ((h.heat_index - 20) / 30) * 100))}%` }} />
                {h.time.endsWith('T00:00') || h.time.endsWith('T12:00') ? <small>{h.time.endsWith('T00:00') ? dayName(h.time.slice(0, 10), data.today).slice(0, 3) : '12'}</small> : null}
              </span>
            ))}
          </div>
          <ul className="city-list">
            {data.heat.map((d) => (
              <li key={d.date}>
                <b>{dayName(d.date, data.today)}</b>
                <span>
                  feels up to {Math.round(d.peak)} °C at {clock(d.peak_time)} ({d.band}) · UV up to {d.uv_max.toFixed(0)}
                  {d.danger_from && d.danger_to ? ` · avoid outdoor work ${clock(d.danger_from)}–${clock(d.danger_to)}` : ''}
                </span>
              </li>
            ))}
          </ul>
          <div className="lt-key">
            {Object.entries(HEAT_COLORS).map(([label, color]) => (
              <span key={label}>
                <i style={{ background: color }} /> {label}
              </span>
            ))}
          </div>
        </section>
      )}

      {data && data.air.length > 0 && (
        <section className="trip-card">
          <h3>
            <Wind size={15} /> Air you breathe
          </h3>
          {now?.air_advice && <p className="city-advice">{now.air_advice}</p>}
          <div className="city-strip">
            {data.hours.map((h) => {
              const band = airBand(h.pm25)
              return (
                <span key={h.time} title={`${h.time.replace('T', ' ')} · PM2.5 ${h.pm25 !== null ? Math.round(h.pm25) : '–'}`}>
                  <i style={{ background: band ? AIR_COLORS[band] : 'rgba(255,255,255,0.1)', height: `${Math.min(100, Math.max(12, ((h.pm25 ?? 0) / 150) * 100))}%` }} />
                  {h.time.endsWith('T00:00') || h.time.endsWith('T12:00') ? <small>{h.time.endsWith('T00:00') ? dayName(h.time.slice(0, 10), data.today).slice(0, 3) : '12'}</small> : null}
                </span>
              )
            })}
          </div>
          <ul className="city-list">
            {data.air.map((d) => (
              <li key={d.date}>
                <b>{dayName(d.date, data.today)}</b>
                <span>
                  {d.band} · PM2.5 averages {d.pm25_mean}, peaks {d.pm25_max} at {clock(d.worst_time)} · cleanest at {clock(d.cleanest_time)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <Bike size={15} /> Best times to be outdoors
          </h3>
          {data.outdoor.length ? (
            <div className="sea-tides">
              {data.outdoor.map((w) => (
                <span key={w.start}>
                  <small>{dayName(w.start.slice(0, 10), data.today)}</small>
                  <b>
                    {clock(w.start)}–{clock(w.end)}
                  </b>
                  <em>
                    feels {Math.round(w.heat_index)} °C · PM2.5 {w.pm25}
                  </em>
                </span>
              ))}
            </div>
          ) : (
            <p className="rest-none">No comfortable two-hour stretch in the next two days: it is too hot, wet or polluted. Early morning is the least bad.</p>
          )}
          <p className="trip-source">Dry, feels below 32 °C, UV under 8 and PM2.5 at 60 or less, between 5 am and 10 pm. {data.rules}</p>
        </section>
      )}

      <button className="trip-ask" onClick={() => onAsk(`Plan my day in ${place.name}: will my ${commute[0]}:00 and ${commute[1]}:00 commutes get rain or waterlogging, how hot will it feel, how is the air, and when is the best time for a walk or run?`)}>
        <MessageSquareText size={16} /> Ask WeatherGPT to plan my day
      </button>
      {data && <p className="trip-source">{data.source}.</p>}
    </div>
  )
}
