import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { AlertTriangle, ClipboardCopy, FileText, Loader2, MapPinned, MessageSquareText, RefreshCw, Users } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { severityColor } from '../../lib/lightning'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { workApi, type CommandTown, type CommandWorkspace } from '../../lib/work'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

type SortKey = 'score' | 'rain_next_24h' | 'rain_past_24h' | 'gust_max' | 'heat_index_max' | 'population'

const RADII = [50, 100, 150, 250]
const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const SCORE_COLORS = ['#5fd39a', '#ffd166', '#ff9f43', '#ff4d6d']
const scoreColor = (score: number) => SCORE_COLORS[Math.min(3, score)]
const clock = (iso: string | null) => (iso ? iso.slice(11, 16) : '–')

function escape(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
}

function CommandMap({ data }: { data: CommandWorkspace }) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 5, maxZoom: 12 })
    L.tileLayer(BASEMAP, { maxZoom: 12, className: 'radar-basemap', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const dLat = data.radius_km / 111
    const dLon = data.radius_km / (111 * Math.cos((data.centre.lat * Math.PI) / 180))
    map.fitBounds(
      [
        [data.centre.lat - dLat, data.centre.lon - dLon],
        [data.centre.lat + dLat, data.centre.lon + dLon],
      ],
      { padding: [10, 10] },
    )
    L.circle([data.centre.lat, data.centre.lon], { radius: data.radius_km * 1000, color: '#ffffff', weight: 1, opacity: 0.4, dashArray: '4 6', fill: false, interactive: false }).addTo(layer)
    data.official.forEach((w) =>
      w.rings.forEach((ring) =>
        L.polygon(
          ring.map(([lon, lat]) => [lat, lon] as [number, number]),
          { color: severityColor(w.severity), weight: 1.5, fillColor: severityColor(w.severity), fillOpacity: 0.2 },
        )
          .bindTooltip(`<b>${escape(w.event)}</b> · ${escape(w.severity ?? '')}<br>${escape(w.issuer)}`, { sticky: true, className: 'trip-tip' })
          .addTo(layer),
      ),
    )
    data.towns.forEach((t) =>
      L.circleMarker([t.lat, t.lon], { radius: 4 + Math.min(8, Math.sqrt((t.population ?? 20000) / 20000)), color: '#0b0f16', weight: 1.5, fillColor: scoreColor(t.score), fillOpacity: 0.95 })
        .bindTooltip(
          `<b>${escape(t.name)}</b>${t.population ? ` · ${t.population.toLocaleString('en-IN')} people` : ''}<br>Rain next 24 h ${t.rain_next_24h} mm (${t.rain_band.toLowerCase()}) · gusts ${t.gust_max} km/h${t.heat_index_max !== null ? `<br>Heat index ${Math.round(t.heat_index_max)} °C` : ''}${t.warnings.length ? `<br>${t.warnings.length} official warning(s)` : ''}`,
          { direction: 'top', className: 'trip-tip' },
        )
        .addTo(layer),
    )
  }, [data])

  return (
    <div className="trip-map">
      <div ref={holder} className="trip-map-canvas" />
      <div className="trip-map-legend">
        <span>
          <i style={{ background: SCORE_COLORS[0] }} /> normal
        </span>
        <span>
          <i style={{ background: SCORE_COLORS[1] }} /> watch
        </span>
        <span>
          <i style={{ background: SCORE_COLORS[2] }} /> alert
        </span>
        <span>
          <i style={{ background: SCORE_COLORS[3] }} /> act
        </span>
      </div>
    </div>
  )
}

export default function CommandView({ place, online, onAsk }: Props) {
  const [data, setData] = useState<CommandWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [radius, setRadius] = useState(100)
  const [sort, setSort] = useState<SortKey>('score')
  const [copied, setCopied] = useState(false)
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache(`command-${radius}`, place.lat, place.lon, () => workApi.command(place.lat, place.lon, radius), online)
      setData(result.data)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, radius, online])

  useEffect(() => {
    load()
  }, [load])

  const ready = data?.available && Array.isArray(data.towns) ? data : null
  const towns = useMemo(() => {
    if (!ready) return []
    const value = (t: CommandTown) => (sort === 'heat_index_max' ? (t.heat_index_max ?? 0) : sort === 'population' ? (t.population ?? 0) : t[sort])
    return [...ready.towns].sort((a, b) => value(b) - value(a))
  }, [ready, sort])

  if (!place) return <div className="cy"><p className="trip-step">Pick your district headquarters to open the board.</p></div>

  const copy = async () => {
    if (!ready) return
    try {
      await navigator.clipboard.writeText(ready.sitrep)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }

  const s = ready?.summary

  return (
    <div className="cy cmd">
      <header className="trip-head cy-head">
        <h1>Command board</h1>
        <p>Every town around {place.name} ranked by what the next 24 hours bring, official warning areas, people exposed and a ready situation report.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh command board">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      <div className="chips">
        {RADII.map((r) => (
          <button key={r} className={radius === r ? 'on' : ''} onClick={() => setRadius(r)}>
            {r} km
          </button>
        ))}
      </div>

      {loading && !data && <p className="trip-step">Scanning towns, warnings and cyclones…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {data && !data.available && <p className="trip-error">{data.reason}</p>}
      {savedAt && <p className="trip-saved">Showing the board saved {savedAgo(savedAt)}. Refresh before acting on it.</p>}

      {ready && s && (
        <>
          <div className="cy-stats">
            <span style={{ borderTop: `3px solid ${s.flagged ? '#ff4d6d' : '#5fd39a'}` }}>
              <small>Towns needing attention</small>
              <b>
                {s.flagged} of {s.towns}
              </b>
            </span>
            <span>
              <small>
                <Users size={11} /> People in flagged towns
              </small>
              <b>{s.population_flagged.toLocaleString('en-IN')}</b>
              <em>of {s.population_scanned.toLocaleString('en-IN')} scanned</em>
            </span>
            <span>
              <small>Official warnings here</small>
              <b>{ready.official.length}</b>
              <em>{s.warned_towns} towns covered</em>
            </span>
            <span>
              <small>Heavy rain towns, 24 h</small>
              <b>{s.heavy_towns}</b>
              <em>area average {s.area_rain_next_24h} mm</em>
            </span>
            <span>
              <small>Wettest next 24 h</small>
              <b>{s.wettest.rain_next_24h} mm</b>
              <em>{s.wettest.name}</em>
            </span>
            <span>
              <small>Wettest last 24 h</small>
              <b>{s.wettest_past.rain_past_24h} mm</b>
              <em>{s.wettest_past.name}</em>
            </span>
            <span>
              <small>Strongest gusts</small>
              <b>{s.windiest.gust_max} km/h</b>
              <em>{s.windiest.name}</em>
            </span>
            <span>
              <small>Thunderstorm towns</small>
              <b>{s.thunder_towns}</b>
            </span>
          </div>

          {ready.storms.length > 0 && (
            <section className="cy-official">
              {ready.storms.map((st, k) => (
                <article key={k}>
                  <em>Active cyclone</em>
                  <b>
                    {st.name} · {st.now.grade?.label ?? 'system'}
                  </b>
                  <p>
                    {st.impact.distance_now_km} km {st.impact.direction_now} now{st.impact.closest ? `; closest approach ${st.impact.closest.km} km` : ''}.
                  </p>
                </article>
              ))}
            </section>
          )}

          <CommandMap data={ready} />

          {ready.official.length > 0 && (
            <section className="trip-card">
              <h3>
                <AlertTriangle size={15} /> Official warnings over this area
              </h3>
              <ul className="lt-warnings">
                {ready.official.map((w) => (
                  <li key={w.id}>
                    <div className="map-warning">
                      <i style={{ background: severityColor(w.severity) }} />
                      <span>
                        <b>
                          {w.event} · {w.severity}
                        </b>
                        <small>
                          {w.issuer} · until {clock(w.expires)} · {w.towns.length ? `covers ${w.towns.slice(0, 6).join(', ')}${w.towns.length > 6 ? ` and ${w.towns.length - 6} more` : ''}` : w.areas.join(', ').slice(0, 100)}
                        </small>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="trip-card">
            <h3>
              <MapPinned size={15} /> Towns, worst first
            </h3>
            <div className="acc-table-wrap">
              <table className="acc-table cmd-table">
                <thead>
                  <tr>
                    <th>Town</th>
                    {(
                      [
                        ['score', 'Risk'],
                        ['rain_next_24h', 'Rain next 24 h'],
                        ['rain_past_24h', 'Last 24 h'],
                        ['gust_max', 'Gusts'],
                        ['heat_index_max', 'Heat index'],
                        ['population', 'People'],
                      ] as [SortKey, string][]
                    ).map(([key, label]) => (
                      <th key={key}>
                        <button className={sort === key ? 'on' : ''} onClick={() => setSort(key)}>
                          {label}
                          {sort === key ? ' ▾' : ''}
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(showAll ? towns : towns.slice(0, 15)).map((t) => (
                    <tr key={`${t.name}-${t.lat}`}>
                      <td>
                        <b>{t.name}</b>
                        <small>
                          {t.km} km {t.direction}
                          {t.warnings.length ? ` · ${t.warnings.map((w) => w.event).join(', ')}` : ''}
                        </small>
                      </td>
                      <td>
                        <i className="cmd-dot" style={{ background: scoreColor(t.score) }} /> {t.score}
                      </td>
                      <td>
                        {t.rain_next_24h} mm<small>{t.rain_band}{t.max_hourly_time ? ` · peak ${clock(t.max_hourly_time)}` : ''}</small>
                      </td>
                      <td>{t.rain_past_24h} mm</td>
                      <td>{t.gust_max} km/h</td>
                      <td>{t.heat_index_max !== null ? `${Math.round(t.heat_index_max)} °C` : '–'}</td>
                      <td>{t.population ? t.population.toLocaleString('en-IN') : '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {towns.length > 15 && (
              <button className="add-btn wide" onClick={() => setShowAll((v) => !v)}>
                {showAll ? 'Show the top 15' : `Show all ${towns.length} towns`}
              </button>
            )}
            <p className="trip-source">{ready.rules}</p>
          </section>

          <section className="trip-card">
            <h3>
              <FileText size={15} /> Situation report
            </h3>
            <pre className="cmd-sitrep">{ready.sitrep}</pre>
            <button className="add-btn" onClick={copy}>
              <ClipboardCopy size={14} /> {copied ? 'Copied' : 'Copy report'}
            </button>
          </section>
        </>
      )}

      <button
        className="trip-ask"
        onClick={() => onAsk(`I am a disaster management officer for ${place.name}. Based on the official warnings and the forecast for the next 72 hours, which areas need attention first, and what preparedness actions should I order now?`)}
      >
        <MessageSquareText size={16} /> Ask WeatherGPT for priorities
      </button>
      {ready && <p className="trip-source">{ready.source}.</p>}
    </div>
  )
}
