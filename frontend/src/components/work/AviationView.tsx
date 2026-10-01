import { AlertTriangle, ArrowUp, Clock, Gauge, Layers, Loader2, MessageSquareText, Plane, PlaneLanding, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { workApi, type AviationWorkspace, type FlightCategory } from '../../lib/work'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const CATEGORY_COLORS: Record<FlightCategory, string> = { VFR: '#5fd39a', MVFR: '#6fb7ff', IFR: '#ff4d6d', LIFR: '#d05cff' }
const CATEGORY_WORDS: Record<FlightCategory, string> = {
  VFR: 'Visual flying conditions',
  MVFR: 'Marginal visual conditions',
  IFR: 'Instrument conditions',
  LIFR: 'Low instrument conditions',
}
const utc = (iso: string) => `${iso.slice(11, 16)}Z`
const ist = (iso: string) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })

export default function AviationView({ place, online, onAsk }: Props) {
  const [data, setData] = useState<AviationWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [icao, setIcao] = useState<string | null>(null)
  const [frame, setFrame] = useState(0)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache(`aviation-${icao ?? 'near'}`, place.lat, place.lon, () => workApi.aviation(place.lat, place.lon, icao), online)
      setData(result.data)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, icao, online])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => setIcao(null), [place?.lat, place?.lon])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to see its airfield weather.</p></div>

  const ready = data?.available && data.airport ? data : null
  const field = ready?.airport
  const metar = field?.metar
  const category = metar?.category ?? null
  const aloft = ready?.aloft.frames[Math.min(frame, (ready?.aloft.frames.length ?? 1) - 1)]

  return (
    <div className="cy avi">
      <header className="trip-head cy-head">
        <h1>Your airfield</h1>
        <p>Decoded reports and forecasts, runway winds, winds aloft and SIGMETs for the airport nearest {place.name}.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh aviation weather">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {loading && !data && <p className="trip-step">Fetching METAR, TAF and winds aloft…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {data && !data.available && <p className="trip-error">{data.reason}</p>}
      {savedAt && <p className="trip-saved">Showing aviation weather saved {savedAgo(savedAt)}. Do not use it for flight.</p>}

      {ready && (
        <div className="chips" role="radiogroup" aria-label="Airport">
          {ready.choices
            .filter((c) => c.reports || c.icao === field?.icao)
            .slice(0, 6)
            .map((c) => (
              <button key={c.icao} role="radio" aria-checked={c.icao === field?.icao} className={c.icao === field?.icao ? 'on' : ''} onClick={() => setIcao(c.icao)}>
                {c.iata ?? c.icao}
                {c.km !== null ? ` · ${c.km} km` : ''}
              </button>
            ))}
        </div>
      )}

      {field && (
        <section className="avi-hero" style={{ borderColor: category ? CATEGORY_COLORS[category] : undefined }}>
          <div>
            <em style={{ background: category ? CATEGORY_COLORS[category] : 'var(--line-2)' }}>{category ?? 'No report'}</em>
            <span>
              <b>
                {field.name} ({field.icao}
                {field.iata ? ` / ${field.iata}` : ''})
              </b>
              <small>
                {category ? CATEGORY_WORDS[category] : 'This airport is not reporting right now'}
                {metar?.observed ? ` · observed ${ist(metar.observed)} IST` : ''}
                {field.elevation_ft !== null ? ` · elevation ${Math.round(field.elevation_ft)} ft` : ''}
              </small>
            </span>
          </div>
          {metar?.raw && <code>{metar.raw}</code>}
          {metar && (
            <p>
              {[
                metar.decoded.wind && `Wind ${metar.decoded.wind}`,
                metar.decoded.visibility && `visibility ${metar.decoded.visibility}`,
                metar.decoded.weather?.length ? metar.decoded.weather.join(', ') : null,
                metar.decoded.clouds?.length ? `cloud ${metar.decoded.clouds.join(', ')}` : 'no significant cloud',
                metar.decoded.temp_dew && `temperature / dew point ${metar.decoded.temp_dew}`,
                metar.decoded.qnh && `QNH ${metar.decoded.qnh}`,
                metar.decoded.trend,
              ]
                .filter(Boolean)
                .join(' · ')}
              .
            </p>
          )}
        </section>
      )}

      {ready && ready.hazards.length > 0 && (
        <section className="avi-hazards">
          {ready.hazards.map((h, k) => (
            <article key={k} className={h.level}>
              <AlertTriangle size={15} />
              <span>
                <b>{h.title}</b>
                <small>{h.detail}</small>
              </span>
            </article>
          ))}
        </section>
      )}

      {field?.runways && field.runways.length > 0 && (
        <section className="trip-card">
          <h3>
            <PlaneLanding size={15} /> Runway winds
          </h3>
          <div className="acc-table-wrap">
            <table className="acc-table avi-table">
              <thead>
                <tr>
                  <th>Runway</th>
                  <th>Length</th>
                  <th>Head / tail</th>
                  <th>Crosswind</th>
                  <th>In gusts</th>
                </tr>
              </thead>
              <tbody>
                {field.runways.map((r) => (
                  <tr key={r.runway} className={r.favoured ? 'ours' : ''}>
                    <td>
                      {r.runway}
                      {r.favoured ? ' ✓' : ''}
                    </td>
                    <td>{r.length_ft ? `${Math.round(r.length_ft).toLocaleString('en-IN')} ft` : '–'}</td>
                    <td className={r.tailwind ? 'bad' : ''}>
                      {r.headwind_kt >= 0 ? `${r.headwind_kt.toFixed(0)} kt head` : `${Math.abs(r.headwind_kt).toFixed(0)} kt tail`}
                    </td>
                    <td>{r.crosswind_kt.toFixed(0)} kt</td>
                    <td className={r.gust_crosswind_kt >= 15 ? 'bad' : ''}>{r.gust_crosswind_kt.toFixed(0)} kt</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {field.density && (
            <div className="cy-stats">
              <span>
                <small>
                  <Gauge size={11} /> Density altitude
                </small>
                <b>{field.density.density_altitude_ft.toLocaleString('en-IN')} ft</b>
                <em>{(field.density.density_altitude_ft - field.density.elevation_ft).toLocaleString('en-IN')} ft above the field</em>
              </span>
              <span>
                <small>Pressure altitude</small>
                <b>{field.density.pressure_altitude_ft.toLocaleString('en-IN')} ft</b>
              </span>
              <span>
                <small>ISA deviation</small>
                <b>
                  {field.density.isa_deviation_c > 0 ? '+' : ''}
                  {field.density.isa_deviation_c} °C
                </b>
              </span>
            </div>
          )}
          <p className="trip-source">Components from the reported wind against true runway headings. ✓ marks the runway with the most headwind.</p>
        </section>
      )}

      {field?.taf && field.taf.periods.length > 0 && (
        <section className="trip-card">
          <h3>
            <Clock size={15} /> Airport forecast (TAF)
          </h3>
          <ul className="avi-taf">
            {field.taf.periods.map((p, k) => (
              <li key={k}>
                <em style={{ background: CATEGORY_COLORS[p.category] }}>{p.category}</em>
                <span>
                  <b>
                    {utc(p.from)}–{utc(p.to)} <i>({ist(p.from)}–{ist(p.to)} IST)</i>
                    {p.change ? ` · ${p.change}` : ''}
                    {p.probability ? ` · ${p.probability}%` : ''}
                  </b>
                  <small>
                    {p.wind_kt !== null ? `wind ${p.wind_dir ?? 'VRB'}° ${p.wind_kt} kt${p.gust_kt ? ` gusting ${p.gust_kt}` : ''} · ` : ''}
                    {p.visibility_km !== null ? `vis ${p.visibility_km} km · ` : ''}
                    {p.ceiling_ft !== null ? `ceiling ${p.ceiling_ft} ft` : 'no ceiling'}
                    {p.weather ? ` · ${p.weather}` : ''}
                    {p.thunder ? ' · thunderstorm' : ''}
                  </small>
                </span>
              </li>
            ))}
          </ul>
          <code className="avi-raw">{field.taf.raw}</code>
        </section>
      )}

      {ready && aloft && (
        <section className="trip-card">
          <h3>
            <Layers size={15} /> Winds and temperatures aloft
          </h3>
          <div className="chips">
            {ready.aloft.frames.map((f, k) => (
              <button key={f.time} className={k === frame ? 'on' : ''} onClick={() => setFrame(k)}>
                {k === 0 ? 'Now' : `+${k * 6} h`}
              </button>
            ))}
          </div>
          <div className="acc-table-wrap">
            <table className="acc-table avi-table">
              <thead>
                <tr>
                  <th>Level</th>
                  <th>Altitude</th>
                  <th>Wind</th>
                  <th>Temp</th>
                </tr>
              </thead>
              <tbody>
                {[...aloft.levels].reverse().map((l) => (
                  <tr key={l.level}>
                    <td>{l.level}</td>
                    <td>{l.altitude_ft !== null ? `${l.altitude_ft.toLocaleString('en-IN')} ft` : '–'}</td>
                    <td>
                      {l.wind_dir !== null && <ArrowUp size={12} style={{ transform: `rotate(${l.wind_dir + 180}deg)` }} />} {l.wind_dir !== null ? `${String(Math.round(l.wind_dir)).padStart(3, '0')}°` : '–'} / {l.wind_kt ?? '–'} kt
                    </td>
                    <td>{l.temp_c !== null ? `${l.temp_c} °C` : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Freezing level {aloft.freezing_level_ft !== null ? `${aloft.freezing_level_ft.toLocaleString('en-IN')} ft` : 'unknown'}; instability (CAPE) {aloft.cape !== null ? Math.round(aloft.cape) : '–'} J/kg at {utc(aloft.time)}.
          </p>
        </section>
      )}

      {ready && ready.alternates.length > 0 && (
        <section className="trip-card">
          <h3>
            <Plane size={15} /> Nearby airports
          </h3>
          <ul className="avi-taf">
            {ready.alternates.map((a) => (
              <li key={a.icao}>
                <em style={{ background: a.category ? CATEGORY_COLORS[a.category] : 'rgba(255,255,255,0.15)' }}>{a.category ?? '–'}</em>
                <span>
                  <b>
                    {a.city ?? a.name} ({a.iata ?? a.icao}) · {a.km} km
                  </b>
                  <small>
                    {[a.wind && `wind ${a.wind}`, a.visibility_km !== null && `vis ${a.visibility_km} km`, a.ceiling_ft !== null ? `ceiling ${a.ceiling_ft} ft` : 'no ceiling'].filter(Boolean).join(' · ')}
                  </small>
                  {a.raw && <code>{a.raw}</code>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ready && ready.sigmets.length > 0 && (
        <section className="trip-card">
          <h3>
            <AlertTriangle size={15} /> SIGMETs over Indian airspace
          </h3>
          <ul className="avi-taf">
            {ready.sigmets.map((s, k) => (
              <li key={k}>
                <em style={{ background: s.near ? '#ff4d6d' : 'rgba(255,255,255,0.18)', color: s.near ? '#0b0f16' : 'var(--ink)' }}>{s.near ? 'NEAR' : s.fir}</em>
                <span>
                  <b>
                    {s.hazard} · {s.fir_name || s.fir} FIR
                  </b>
                  <small>
                    valid {utc(s.from)}–{utc(s.to)}
                    {s.top_ft ? ` · tops FL${Math.round(s.top_ft / 100)}` : ''}
                    {s.qualifier ? ` · ${s.qualifier}` : ''}
                  </small>
                  {s.raw && <code>{s.raw}</code>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button
        className="trip-ask"
        onClick={() => onAsk(`Give me a pilot's weather briefing for ${field ? `${field.name} (${field.icao})` : place.name}: current conditions, the TAF in plain words, runway and crosswind, winds aloft and any thunderstorm, turbulence or icing risk in the next 12 hours.`)}
      >
        <MessageSquareText size={16} /> Ask WeatherGPT for a briefing
      </button>
      {ready && <p className="trip-source">{ready.source}</p>}
    </div>
  )
}
