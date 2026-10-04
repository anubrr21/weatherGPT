import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  AlertTriangle,
  Anchor,
  Boxes,
  Check,
  ClipboardCopy,
  Clock,
  Loader2,
  MessageSquareText,
  Network,
  Package,
  Plane,
  Plug,
  Plus,
  RefreshCw,
  Route as RouteIcon,
  ShieldCheck,
  Ship,
  Thermometer,
  TrainFront,
  Trash2,
  Truck,
  Warehouse,
  type LucideIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { severityColor } from '../../lib/lightning'
import {
  API_ORIGIN,
  LEVEL_COLORS,
  VERDICT_COLORS,
  dayOf,
  hourOf,
  levelColor,
  loadFleet,
  loadSites,
  logisticsApi,
  parseFleetLines,
  reportUrl,
  riskColor,
  saveFleet,
  saveSites,
  span,
  when,
  type FleetResult,
  type Lane,
  type LogiMode,
  type LogiOptions,
  type LogiPoint,
  type LogiRoute,
  type NetworkResult,
  type ShipmentRequest,
  type ShipmentResult,
  type Site,
  type SitesResult,
} from '../../lib/logistics'
import type { Place } from '../../lib/types'
import Markdown from '../Markdown'
import PdfButton from '../PdfButton'
import PlaceInput from '../trip/PlaceInput'
import './logistics.css'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

type Tab = 'shipment' | 'fleet' | 'network' | 'sites' | 'connect'

const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const MODE_ICONS: Record<LogiMode, LucideIcon> = { road: Truck, rail: TrainFront, air: Plane, sea: Ship }
const SITE_ICONS: Record<Site['kind'], LucideIcon> = { port: Anchor, airport: Plane, hub: Warehouse }
const TABS: { id: Tab; label: string; icon: LucideIcon }[] = [
  { id: 'shipment', label: 'Shipment', icon: Package },
  { id: 'fleet', label: 'Fleet board', icon: Boxes },
  { id: 'network', label: 'Corridors', icon: Network },
  { id: 'sites', label: 'Ports & hubs', icon: Warehouse },
  { id: 'connect', label: 'Connect', icon: Plug },
]
const FALLBACK: LogiOptions = {
  modes: [
    { id: 'road', label: 'Road' },
    { id: 'rail', label: 'Rail' },
    { id: 'air', label: 'Air' },
    { id: 'sea', label: 'Sea' },
  ],
  vehicles: [
    { id: 'lcv', label: 'Light truck (LCV)' },
    { id: 'hcv', label: 'Heavy truck (HCV)' },
    { id: 'container', label: 'Container trailer' },
    { id: 'tanker', label: 'Tanker' },
    { id: 'reefer', label: 'Reefer truck' },
  ],
  cargo: [
    { id: 'general', label: 'General cargo' },
    { id: 'chilled', label: 'Chilled (2 to 8 °C)' },
    { id: 'frozen', label: 'Frozen (-18 °C or below)' },
    { id: 'pharma', label: 'Pharma, room temperature (15 to 25 °C)' },
    { id: 'produce', label: 'Fresh produce, no cooling' },
    { id: 'moisture', label: 'Moisture-sensitive (cement, grain, paper, textiles)' },
    { id: 'electronics', label: 'Electronics and fragile goods' },
    { id: 'hazmat', label: 'Flammable or hazardous' },
    { id: 'livestock', label: 'Livestock and poultry' },
  ],
  ports: [],
  hubs: [],
  limits: { fleet: 20, sites: 30, vias: 8 },
}

const escape = (text: string) => text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
const asPlace = (p: Place | null) => (p ? { name: p.name, lat: p.lat, lon: p.lon } : null)

function useMap(minZoom = 4) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom, maxZoom: 12 })
    L.tileLayer(BASEMAP, { maxZoom: 12, className: 'radar-basemap', attribution: ATTRIBUTION }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [minZoom])
  return { holder, mapRef, layerRef }
}

function Legend() {
  return (
    <div className="trip-map-legend">
      {['clear', 'moderate', 'high', 'severe'].map((word, i) => (
        <span key={word}>
          <i style={{ background: LEVEL_COLORS[i] }} /> {word}
        </span>
      ))}
    </div>
  )
}

function pointTip(p: LogiPoint) {
  const w = p.weather
  const lines = [`<b>${escape(p.place ?? `${p.km} km`)}</b> · ${when(p.eta)}`]
  if (w) {
    lines.push(
      [
        w.temp !== null ? `${Math.round(w.temp)} °C` : '',
        escape(w.label),
        w.rain_mmh ? `${w.rain_mmh} mm/h` : '',
        w.gust !== null ? `gusts ${Math.round(w.gust)} km/h` : '',
        w.wave !== null && w.wave !== undefined ? `waves ${w.wave} m` : '',
      ]
        .filter(Boolean)
        .join(' · '),
    )
  }
  for (const h of p.hazards ?? []) lines.push(escape(h.detail))
  if (p.slow_pct) lines.push(`Speed down about ${p.slow_pct}%`)
  return lines.join('<br>')
}

function RouteMap({ route }: { route: LogiRoute }) {
  const { holder, mapRef, layerRef } = useMap()
  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    const line = route.geometry
    if (!map || !layer || !line?.length) return
    layer.clearLayers()
    const nearest = (p: LogiPoint) => {
      let best = 0
      let gap = Infinity
      line.forEach(([lat, lon], k) => {
        const d = (lat - p.lat) ** 2 + (lon - p.lon) ** 2
        if (d < gap) {
          gap = d
          best = k
        }
      })
      return best
    }
    const marks = route.points.map(nearest)
    L.polyline(line, { color: '#0b0f16', weight: 7, opacity: 0.55, interactive: false }).addTo(layer)
    route.points.slice(0, -1).forEach((p, k) => {
      const piece = line.slice(marks[k], Math.max(marks[k] + 2, marks[k + 1] + 1))
      L.polyline(piece, { color: levelColor(Math.max(p.level, route.points[k + 1].level)), weight: 4.5, opacity: 0.95, interactive: false }).addTo(layer)
    })
    route.points.forEach((p, k) => {
      const end = k === 0 || k === route.points.length - 1
      if (!end && p.level < 1 && k % 3) return
      L.circleMarker([p.lat, p.lon], { radius: end ? 7 : p.level >= 1 ? 5.5 : 3.5, color: '#0b0f16', weight: 1.5, fillColor: end ? '#ffffff' : levelColor(p.level), fillOpacity: 1 })
        .bindTooltip(pointTip(p), { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    })
    route.rests.forEach((r) => {
      const at = route.points.reduce((a, b) => (Math.abs(b.km - r.km) < Math.abs(a.km - r.km) ? b : a))
      L.circleMarker([at.lat, at.lon], { radius: 6, color: '#8fd3ff', weight: 2, fillColor: '#0b0f16', fillOpacity: 1 })
        .bindTooltip(`<b>${r.kind === 'halt' ? 'Overnight halt' : 'Driver break'}</b> · ${span(r.minutes)}<br>${when(r.at)}${r.near ? ` near ${escape(r.near)}` : ''}`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    })
    map.fitBounds(L.latLngBounds(line), { padding: [24, 24] })
  }, [route, mapRef, layerRef])
  return (
    <div className="trip-map">
      <div ref={holder} className="trip-map-canvas" />
      <Legend />
    </div>
  )
}

function DepartureChart({ route, onPick }: { route: LogiRoute; onPick: (iso: string) => void }) {
  const scan = route.departures
  if (scan.length < 3) return null
  const peak = Math.max(30, ...scan.map((d) => d.delay_min))
  const best = route.best_departure?.depart
  return (
    <section className="trip-card">
      <h3>
        <Clock size={15} /> Best time to dispatch, next {Math.round((new Date(scan[scan.length - 1].depart).getTime() - new Date(scan[0].depart).getTime()) / 3600000)} hours
      </h3>
      {route.best_departure ? <p className="lg-note good">{route.best_departure.why}</p> : <p className="lg-note">Dispatching at the chosen time is as good as any other in this window.</p>}
      <div className="lg-scan" role="list">
        {scan.map((d, k) => (
          <button
            key={d.depart}
            role="listitem"
            className={`${k === 0 ? 'now' : ''} ${d.depart === best ? 'best' : ''}`}
            style={{ ['--h' as string]: `${12 + (d.delay_min / peak) * 58}px`, ['--c' as string]: riskColor(d.risk) }}
            onClick={() => onPick(d.depart)}
            title={`Dispatch ${when(d.depart)} · arrive ${when(d.arrive)} · ${d.risk.toLowerCase()} risk · ${d.delay_min} min weather delay`}
            aria-label={`Dispatch ${when(d.depart)}, ${d.risk} risk, ${d.delay_min} minutes weather delay`}
          >
            <i />
            {k % Math.max(1, Math.round(scan.length / 6)) === 0 ? <small>{k === 0 ? 'chosen' : hourOf(d.depart)}</small> : <small />}
          </button>
        ))}
      </div>
      <p className="trip-source">Bar height is the weather delay; colour is the risk on the route. Tap a bar to assess that dispatch time.</p>
    </section>
  )
}

function ShipmentPanel({ place, options, onAsk, onSave }: { place: Place | null; options: LogiOptions; onAsk: (text: string) => void; onSave: (request: ShipmentRequest) => void }) {
  const [from, setFrom] = useState<Place | null>(place)
  const [to, setTo] = useState<Place | null>(null)
  const [mode, setMode] = useState<LogiMode>('road')
  const [vehicle, setVehicle] = useState('hcv')
  const [cargo, setCargo] = useState('general')
  const [crew, setCrew] = useState(1)
  const [depart, setDepart] = useState('')
  const [result, setResult] = useState<ShipmentResult | null>(null)
  const [index, setIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [sent, setSent] = useState<ShipmentRequest | null>(null)
  const [brief, setBrief] = useState<{ text: string; model: string | null } | null>(null)
  const [briefing, setBriefing] = useState(false)
  const [showLog, setShowLog] = useState(false)

  const request = useCallback(
    (at?: string): ShipmentRequest | null => {
      const origin = asPlace(from)
      const destination = asPlace(to)
      if (!origin || !destination) return null
      return { origin, destination, mode, vehicle, cargo, crew, depart: at ?? (depart ? new Date(depart).toISOString() : null) }
    },
    [from, to, mode, vehicle, cargo, crew, depart],
  )

  const assess = async (at?: string) => {
    const body = request(at)
    if (!body) return
    setLoading(true)
    setError(null)
    setSaved(false)
    setBrief(null)
    try {
      const found = await logisticsApi.shipment(body)
      const fixed = { ...body, depart: found.routes[0]?.depart ?? body.depart }
      setResult(found)
      setSent(fixed)
      setIndex(0)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const route = result?.routes[index]
  const ready = Boolean(from && to)
  const sentKey = sent ? JSON.stringify(sent) : ''

  useEffect(() => {
    if (!sent || !result) return
    let live = true
    setBriefing(true)
    setBrief(null)
    logisticsApi
      .analysis(sent, index)
      .then((found) => live && setBrief(found))
      .catch(() => live && setBrief(null))
      .finally(() => live && setBriefing(false))
    return () => {
      live = false
    }
  }, [sentKey, index])

  const pdf = sent && result ? reportUrl('shipment', sent, { route: index }) : null

  return (
    <>
      <section className="trip-card lg-form">
        <div className="lg-modes">
          {options.modes.map((m) => {
            const Icon = MODE_ICONS[m.id]
            return (
              <button key={m.id} className={mode === m.id ? 'on' : ''} onClick={() => setMode(m.id)}>
                <Icon size={16} /> {m.label}
              </button>
            )
          })}
        </div>
        <PlaceInput label="From" value={from} onChange={setFrom} current={place} />
        <PlaceInput label="To" value={to} onChange={setTo} />
        <div className="lg-fields">
          {mode === 'road' && (
            <label>
              <span>Vehicle</span>
              <select value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
                {options.vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            <span>Cargo</span>
            <select value={cargo} onChange={(e) => setCargo(e.target.value)}>
              {options.cargo.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          {mode === 'road' && (
            <label>
              <span>Drivers</span>
              <select value={crew} onChange={(e) => setCrew(Number(e.target.value))}>
                <option value={1}>One driver</option>
                <option value={2}>Two drivers</option>
              </select>
            </label>
          )}
          <label>
            <span>Dispatch</span>
            <input type="datetime-local" value={depart} onChange={(e) => setDepart(e.target.value)} />
          </label>
        </div>
        {mode === 'sea' && <p className="trip-source">Sea legs run between the Indian ports nearest to the two places.</p>}
        <button className="lg-go" disabled={!ready || loading} onClick={() => assess()}>
          {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
          {loading ? 'Reading the weather along the route…' : 'Assess shipment'}
        </button>
        {error && <p className="trip-error">{error}</p>}
      </section>

      {result && route && (
        <>
          <section className="lg-verdict" style={{ ['--c' as string]: VERDICT_COLORS[route.verdict.code] }}>
            <div>
              <em>
                {result.mode_label}
                {result.vehicle_label ? ` · ${result.vehicle_label}` : ''} · {result.cargo_label}
              </em>
              <b>{route.verdict.label}</b>
              <ul>
                {route.verdict.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
            <span>
              {result.origin.name} → {result.destination.name}
              <small>{route.summary}</small>
              {pdf && <PdfButton url={pdf} name="WeatherGPT-shipment.pdf" label="Download PDF report" />}
            </span>
          </section>

          <section className="trip-card">
            <h3>
              <ShieldCheck size={15} /> Summary
            </h3>
            {route.narrative.map((line) => (
              <p key={line} className="lg-para">
                {line}
              </p>
            ))}
          </section>

          {result.routes.length > 1 && (
            <div className="chips">
              {result.routes.map((r, k) => (
                <button key={k} className={k === index ? 'on' : ''} onClick={() => setIndex(k)}>
                  {r.summary} · {span(r.duration_min)}
                </button>
              ))}
            </div>
          )}

          <div className="cy-stats">
            <span style={{ borderTop: `3px solid ${riskColor(route.risk.label)}` }}>
              <small>Expected arrival</small>
              <b>{when(route.arrive)}</b>
              <em>{span(route.duration_min)} door to door</em>
            </span>
            <span>
              <small>Weather delay</small>
              <b>{route.delay_min ? span(route.delay_min) : 'None'}</b>
              <em>{route.delay_worst_min > route.delay_min ? `up to ${span(route.delay_worst_min)}; latest ${when(route.arrive_latest)}` : 'no slow stretches forecast'}</em>
            </span>
            <span>
              <small>Distance</small>
              <b>{Math.round(route.distance_km).toLocaleString('en-IN')} km</b>
              <em>{span(route.base_min)} moving in clear weather</em>
            </span>
            {result.mode === 'road' && (
              <span>
                <small>Driver rest</small>
                <b>{route.rest_min ? span(route.rest_min) : 'None'}</b>
                <em>
                  {route.rests.filter((r) => r.kind === 'halt').length} halts · {route.rests.filter((r) => r.kind === 'break').length} breaks
                </em>
              </span>
            )}
            <span>
              <small>Route risk</small>
              <b>{route.risk.label}</b>
              <em>{Math.round(route.night_share * 100)}% of the trip in darkness</em>
            </span>
            <span style={{ borderTop: `3px solid ${route.cargo.status === 'risk' ? '#ff4d6d' : route.cargo.status === 'watch' ? '#ffd166' : '#5fd39a'}` }}>
              <small>Cargo</small>
              <b>{route.cargo.status === 'risk' ? 'At risk' : route.cargo.status === 'watch' ? 'Watch' : 'Safe'}</b>
              <em>{route.cargo.label}</em>
            </span>
          </div>

          {route.geometry && <RouteMap route={route} />}

          {route.actions.length > 0 && (
            <section className="trip-card">
              <h3>
                <ShieldCheck size={15} /> What to do
              </h3>
              <ul className="lg-list">
                {route.actions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </section>
          )}

          <section className="trip-card">
            <h3>
              <MessageSquareText size={15} /> WeatherGPT analysis
            </h3>
            {briefing && (
              <p className="lg-note">
                <Loader2 size={13} className="spin" /> Writing the detailed briefing…
              </p>
            )}
            {brief && <Markdown text={brief.text} />}
            {!briefing && !brief && <p className="lg-note">The written briefing is unavailable right now; the figures on this page are complete without it.</p>}
          </section>

          <section className="trip-card">
            <h3>
              <Clock size={15} /> Where the delay and risk come from
            </h3>
            {route.breakdown.length === 0 ? (
              <p className="lg-note good">No weather on this route slows the shipment or reaches a hazard threshold.</p>
            ) : (
              <div className="acc-table-wrap">
                <table className="acc-table lg-table">
                  <thead>
                    <tr>
                      <th>Cause</th>
                      <th>Severity</th>
                      <th>Distance</th>
                      <th>Time</th>
                      <th>Delay</th>
                    </tr>
                  </thead>
                  <tbody>
                    {route.breakdown.map((row) => (
                      <tr key={row.kind}>
                        <td>
                          <b>
                            <i className="cmd-dot" style={{ background: levelColor(row.level) }} /> {row.label}
                          </b>
                          <small>{row.worst}</small>
                        </td>
                        <td>{row.severity}</td>
                        <td>{row.km} km</td>
                        <td>{row.hours} h</td>
                        <td>{row.delay_min ? span(row.delay_min) : '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="trip-source">
              Forecast confidence: {route.confidence.label.toLowerCase()} ({route.confidence.score} of 100). {route.confidence.note}
            </p>
          </section>

          <DepartureChart
            route={route}
            onPick={(iso) => {
              const local = new Date(new Date(iso).getTime() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)
              setDepart(local)
              assess(iso)
            }}
          />

          <section className="trip-card">
            <h3>
              <RouteIcon size={15} /> Weather on the route when the load passes
            </h3>
            {route.hazards.length === 0 && <p className="lg-note good">No hazardous weather is forecast on any stretch at the time the shipment passes it.</p>}
            <ul className="lg-spans">
              {route.hazards.map((h, k) => (
                <li key={k} style={{ ['--c' as string]: levelColor(h.level) }}>
                  <b>{h.detail}</b>
                  <small>
                    km {Math.round(h.from_km)}
                    {h.to_km > h.from_km ? `–${Math.round(h.to_km)}` : ''}
                    {h.near ? ` · near ${h.near}` : ''} · {when(h.from_eta)}
                    {h.to_eta !== h.from_eta ? ` to ${hourOf(h.to_eta)}` : ''}
                  </small>
                  {h.advice && <p>{h.advice}</p>}
                </li>
              ))}
            </ul>
            {route.rests.length > 0 && (
              <p className="trip-source">
                Rest: {route.rests.map((r) => `${r.kind === 'halt' ? 'halt' : 'break'} ${span(r.minutes)} at km ${Math.round(r.km)}${r.near ? ` (${r.near})` : ''}`).join(' · ')}
              </p>
            )}
          </section>

          {route.top_departures && route.top_departures.length > 1 && (
            <section className="trip-card">
              <h3>
                <Clock size={15} /> Five best dispatch times
              </h3>
              <div className="acc-table-wrap">
                <table className="acc-table lg-table">
                  <thead>
                    <tr>
                      <th>Dispatch</th>
                      <th>Arrival</th>
                      <th>Risk</th>
                      <th>Delay</th>
                      <th>In darkness</th>
                    </tr>
                  </thead>
                  <tbody>
                    {route.top_departures.map((d) => (
                      <tr key={d.depart}>
                        <td>
                          <b>{when(d.depart)}</b>
                        </td>
                        <td>{when(d.arrive)}</td>
                        <td>
                          <i className="cmd-dot" style={{ background: riskColor(d.risk) }} /> {d.risk}
                        </td>
                        <td>{d.delay_min ? span(d.delay_min) : 'None'}</td>
                        <td>{Math.round(d.night * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {route.stages && route.stages.length > 0 && (
            <section className="trip-card">
              <h3>
                <RouteIcon size={15} /> Stage by stage
              </h3>
              <ul className="lg-daylist lg-stages">
                {route.stages.map((st) => (
                  <li key={st.from_km} style={{ ['--c' as string]: levelColor(st.level) }}>
                    <b>
                      km {Math.round(st.from_km)}–{Math.round(st.to_km)}
                    </b>
                    <div>
                      <span>
                        {st.from && st.to ? `${st.from} to ${st.to} · ` : ''}
                        {hourOf(st.from_eta)}–{hourOf(st.to_eta)}
                        {st.night ? ' · night' : ''}
                      </span>
                      <small>
                        {[
                          st.sky,
                          st.temp_min !== null ? `${st.temp_min}–${st.temp_max} °C` : null,
                          `rain ${st.rain_mm} mm`,
                          st.gust_max !== null ? `gusts ${st.gust_max} km/h` : null,
                          st.wave_max !== null ? `waves ${st.wave_max} m` : st.vis_min !== null ? `visibility ${st.vis_min >= 1000 ? `${Math.round(st.vis_min / 1000)} km` : `${st.vis_min} m`}` : null,
                          st.slow_pct ? `speed down ${st.slow_pct}%` : null,
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </small>
                      {st.worst && <small className="why">{st.worst}</small>}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="trip-card">
            <h3>
              <Thermometer size={15} /> Cargo exposure · {route.cargo.label}
            </h3>
            <div className="lg-metrics">
              {route.cargo.metrics.map((m) => (
                <span key={m.label}>
                  <small>{m.label}</small>
                  <b>{m.value}</b>
                </span>
              ))}
            </div>
            {route.cargo.notes.length === 0 && <p className="lg-note good">Nothing in the forecast threatens this cargo on this trip.</p>}
            <ul className="lg-list">
              {route.cargo.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </section>

          {(route.warnings.length > 0 || route.cyclones.length > 0) && (
            <section className="trip-card">
              <h3>
                <AlertTriangle size={15} /> Official warnings and cyclones on the route
              </h3>
              <ul className="lt-warnings">
                {route.cyclones.map((c, k) => (
                  <li key={`c${k}`}>
                    <div className="map-warning">
                      <i style={{ background: '#ff4d6d' }} />
                      <span>
                        <b>Cyclone {c.name ?? 'system'}</b>
                        <small>
                          Passes within {c.closest_km} km of the route near km {Math.round(c.route_km)}
                          {c.closest_time ? ` around ${when(c.closest_time)}` : ''}
                        </small>
                      </span>
                    </div>
                  </li>
                ))}
                {route.warnings.map((w) => (
                  <li key={w.id}>
                    <div className="map-warning">
                      <i style={{ background: severityColor(w.severity) }} />
                      <span>
                        <b>
                          {w.event} · {w.severity}
                        </b>
                        <small>
                          km {w.from_km}–{w.to_km} · {w.issuer}
                          {w.expires ? ` · until ${when(w.expires)}` : ''}
                          {w.active_on_arrival ? '' : ' · expires before the load gets there'}
                        </small>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {route.model_check && route.model_check.length > 0 && (
            <section className="trip-card">
              <h3>
                <ShieldCheck size={15} /> Do the weather models agree?
              </h3>
              <ul className="lg-daylist lg-stages">
                {route.model_check.map((c) => (
                  <li key={c.where} style={{ ['--c' as string]: c.score >= 75 ? LEVEL_COLORS[0] : c.score >= 50 ? LEVEL_COLORS[1] : LEVEL_COLORS[3] }}>
                    <b>{c.where}</b>
                    <div>
                      <span>
                        {c.label} confidence ({c.score} of 100){c.place ? ` · ${c.place}` : ''} · {dayOf(c.date)}
                      </span>
                      <small>
                        Rain: {c.models.filter((m) => m.rain_mm !== null).map((m) => `${m.name} ${m.rain_mm} mm`).join(' · ')} ({c.rain_agreement})
                      </small>
                      <small>
                        Maximum temperature: {c.models.filter((m) => m.tmax !== null).map((m) => `${m.name} ${Math.round(m.tmax!)} °C`).join(' · ')}
                      </small>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {route.extremes && route.extremes.length > 0 && (
            <section className="trip-card">
              <h3>
                <Thermometer size={15} /> Extremes on the route
              </h3>
              <div className="lg-metrics">
                {route.extremes.map((e) => (
                  <span key={e.label}>
                    <small>{e.label}</small>
                    <b>{e.value}</b>
                    <small>
                      km {Math.round(e.km)}
                      {e.place ? ` · ${e.place}` : ''} · {when(e.eta)}
                    </small>
                  </span>
                ))}
              </div>
              {route.other_crew && (
                <p className="trip-source">
                  With {route.other_crew.crew === 2 ? 'two drivers' : 'one driver'} the shipment would arrive {when(route.other_crew.arrive)} after {span(route.other_crew.duration_min)}, with {span(route.other_crew.rest_min)} of rest.
                </p>
              )}
            </section>
          )}

          <section className="trip-card">
            <h3>
              <RouteIcon size={15} /> Full route log
              <button className="lg-inline lg-refresh" onClick={() => setShowLog((v) => !v)}>
                {showLog ? 'Hide' : `Show all ${route.points.length} points`}
              </button>
            </h3>
            {showLog && (
              <div className="acc-table-wrap">
                <table className="acc-table lg-table">
                  <thead>
                    <tr>
                      <th>km</th>
                      <th>ETA</th>
                      <th>Sky</th>
                      <th>°C</th>
                      <th>Rain</th>
                      <th>Gusts</th>
                      <th>{result.mode === 'sea' ? 'Waves' : 'Visibility'}</th>
                      <th>Hazard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {route.points.map((p) => (
                      <tr key={p.km}>
                        <td>
                          <b>
                            <i className="cmd-dot" style={{ background: levelColor(p.level) }} /> {Math.round(p.km)}
                          </b>
                          {p.place && <small>{p.place}</small>}
                        </td>
                        <td>{when(p.eta)}</td>
                        <td>{p.weather?.label ?? '–'}</td>
                        <td>{p.weather?.temp != null ? Math.round(p.weather.temp) : '–'}</td>
                        <td>{p.weather?.rain_mmh != null ? `${p.weather.rain_mmh} mm/h` : '–'}</td>
                        <td>{p.weather?.gust != null ? `${Math.round(p.weather.gust)}` : '–'}</td>
                        <td>
                          {result.mode === 'sea'
                            ? p.weather?.wave != null
                              ? `${p.weather.wave} m`
                              : '–'
                            : p.weather?.visibility != null
                              ? p.weather.visibility >= 1000
                                ? `${Math.round(p.weather.visibility / 1000)} km`
                                : `${Math.round(p.weather.visibility)} m`
                              : '–'}
                        </td>
                        <td>{(p.hazards ?? []).map((h) => h.detail).join('; ') || '–'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!showLog && <p className="lg-note">The forecast at every sample point for the hour the shipment is expected there. It is also in the PDF report.</p>}
          </section>

          <div className="lg-row">
            {pdf && <PdfButton url={pdf} name="WeatherGPT-shipment.pdf" label="Download PDF report" />}
            <button
              className="add-btn"
              onClick={() => {
                const body = request()
                if (!body) return
                onSave({ ...body, ref: `${result.origin.name} → ${result.destination.name}` })
                setSaved(true)
              }}
            >
              {saved ? <Check size={14} /> : <Plus size={14} />} {saved ? 'On the fleet board' : 'Add to fleet board'}
            </button>
            <button
              className="add-btn"
              onClick={() =>
                onAsk(
                  `Assess a ${result.mode_label.toLowerCase()} shipment of ${result.cargo_label.toLowerCase()} from ${result.origin.name} to ${result.destination.name}${result.vehicle_label ? ` on a ${result.vehicle_label.toLowerCase()}` : ''}, dispatching ${when(route.depart)}. What are the main weather risks and what should the dispatcher do?`,
                )
              }
            >
              <MessageSquareText size={14} /> Ask WeatherGPT
            </button>
          </div>
          <p className="trip-source">
            {route.source}. {result.method.eta} {result.mode === 'road' ? `${result.method.road_speed} ${result.method.driver_hours} ` : ''}
            {result.method.limits}
          </p>
        </>
      )}
    </>
  )
}

function FleetPanel({ fleet, setFleet, options, online }: { fleet: ShipmentRequest[]; setFleet: (list: ShipmentRequest[]) => void; options: LogiOptions; online: boolean }) {
  const [data, setData] = useState<FleetResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [paste, setPaste] = useState('')
  const [note, setNote] = useState<string | null>(null)
  const key = JSON.stringify(fleet)

  const load = useCallback(async () => {
    if (!fleet.length) {
      setData(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      setData(await logisticsApi.fleet(fleet))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [key])

  useEffect(() => {
    load()
  }, [load])

  const add = () => {
    const { rows, skipped } = parseFleetLines(
      paste,
      options.vehicles.map((v) => v.id),
      options.cargo.map((c) => c.id),
    )
    if (!rows.length) {
      setNote('No shipments found. Use one line per shipment: reference, from, to.')
      return
    }
    const room = options.limits.fleet - fleet.length
    setFleet([...fleet, ...rows.slice(0, room)])
    setPaste('')
    setNote(`${Math.min(rows.length, room)} added${rows.length > room ? `, ${rows.length - room} left out (the board holds ${options.limits.fleet})` : ''}${skipped ? `, ${skipped} lines skipped` : ''}.`)
  }

  const s = data?.summary
  return (
    <>
      {s && (
        <div className="cy-stats">
          <span style={{ borderTop: `3px solid ${s.hold ? '#ff4d6d' : s.caution ? '#ffd166' : '#5fd39a'}` }}>
            <small>Shipments</small>
            <b>{s.total}</b>
            <em>{s.failed ? `${s.failed} could not be assessed` : 'all assessed'}</em>
          </span>
          <span>
            <small>Go</small>
            <b>{s.go}</b>
          </span>
          <span>
            <small>Go with caution</small>
            <b>{s.caution}</b>
          </span>
          <span>
            <small>Hold or reroute</small>
            <b>{s.hold}</b>
          </span>
          <span>
            <small>Total weather delay</small>
            <b>{s.delay_min ? span(s.delay_min) : 'None'}</b>
          </span>
        </div>
      )}

      <section className="trip-card">
        <h3>
          <Boxes size={15} /> Shipments on the board
          <button className="icon-btn lg-refresh" onClick={load} disabled={loading || !online || !fleet.length} aria-label="Refresh fleet board">
            {loading ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />}
          </button>
        </h3>
        {!fleet.length && <p className="lg-note">Nothing here yet. Assess a shipment and add it, or paste a list below.</p>}
        {error && <p className="trip-error">{error}</p>}
        <ul className="lg-fleet">
          {fleet.map((item, k) => {
            const row = data?.shipments[k]
            const Icon = MODE_ICONS[item.mode]
            return (
              <li key={`${item.ref}-${k}`} style={{ ['--c' as string]: row?.verdict ? VERDICT_COLORS[row.verdict.code] : 'var(--line-2)' }}>
                <Icon size={16} />
                <div>
                  <b>{item.ref ?? `${item.origin.name} → ${item.destination.name}`}</b>
                  <small>
                    {item.origin.name} → {item.destination.name}
                    {row?.ok ? ` · ${Math.round(row.distance_km ?? 0)} km · ${row.cargo_label}` : ''}
                  </small>
                  {row?.ok && row.verdict && (
                    <small>
                      Arrives {when(row.arrive!)}
                      {row.delay_min ? ` · weather delay ${span(row.delay_min)}` : ''}
                      {row.worst ? ` · ${row.worst.detail}${row.worst.near ? ` near ${row.worst.near}` : ''}` : ''}
                      {row.warnings ? ` · ${row.warnings} official warning${row.warnings > 1 ? 's' : ''}` : ''}
                      {row.cargo_status === 'risk' ? ' · cargo at risk' : ''}
                    </small>
                  )}
                  {row && !row.ok && <small className="bad">{row.error}</small>}
                  {row?.best_departure && <small className="good">{row.best_departure.why}</small>}
                </div>
                <em>{row?.verdict?.label ?? (loading ? '…' : '')}</em>
                <button className="icon-btn" onClick={() => setFleet(fleet.filter((_, n) => n !== k))} aria-label="Remove shipment">
                  <Trash2 size={14} />
                </button>
              </li>
            )
          })}
        </ul>
        <p className="trip-source">A dispatch time that has passed is treated as leaving now. The board is kept on this device.</p>
        {fleet.length > 0 && <PdfButton url={reportUrl('fleet', { shipments: fleet })} name="WeatherGPT-fleet.pdf" label="Download the board as PDF" />}
      </section>

      <section className="trip-card">
        <h3>
          <Plus size={15} /> Add many at once
        </h3>
        <textarea
          className="lg-paste"
          rows={4}
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          placeholder={'LR-2041, Pune, Hyderabad, road, reefer, chilled, 2026-10-06T21:00\nLR-2042, Ahmedabad, Mundra Port, road, container\nBL-77, Kochi, Chennai, sea'}
          aria-label="Shipments, one per line"
        />
        <p className="trip-source">One line per shipment: reference, from, to, then optionally mode, vehicle, cargo and dispatch time. Copy the columns straight from a spreadsheet.</p>
        <button className="add-btn" onClick={add} disabled={!paste.trim() || fleet.length >= options.limits.fleet}>
          <Plus size={14} /> Add to board
        </button>
        {note && <p className="lg-note">{note}</p>}
      </section>
    </>
  )
}

function NetworkMap({ lanes, active, onPick }: { lanes: Lane[]; active: string | null; onPick: (id: string) => void }) {
  const { holder, mapRef, layerRef } = useMap()
  const fitted = useRef<L.Map | null>(null)
  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const ordered = [...lanes].sort((a, b) => a.risk.score - b.risk.score)
    ordered.forEach((lane) => {
      const on = lane.id === active
      L.polyline(lane.geometry, { color: levelColor(lane.level), weight: on ? 7 : 3.5, opacity: on || !active ? 0.95 : 0.45 })
        .bindTooltip(`<b>${escape(lane.name)}</b><br>${lane.distance_km} km · ${span(lane.duration_min)}${lane.delay_min ? ` · weather delay ${span(lane.delay_min)}` : ''}${lane.worst ? `<br>${escape(lane.worst.detail)}` : ''}`, { sticky: true, className: 'trip-tip' })
        .on('click', () => onPick(lane.id))
        .addTo(layer)
      lane.segments
        .filter((p) => p.level >= 1)
        .forEach((p) => L.circleMarker([p.lat, p.lon], { radius: 5, color: '#0b0f16', weight: 1.5, fillColor: levelColor(p.level), fillOpacity: 1, interactive: false }).addTo(layer))
    })
    const ends = new Map<string, [number, number]>()
    lanes.forEach((lane) => {
      ends.set(lane.from.name, [lane.from.lat, lane.from.lon])
      ends.set(lane.to.name, [lane.to.lat, lane.to.lon])
    })
    ends.forEach((at, name) => L.circleMarker(at, { radius: 3.5, color: '#0b0f16', weight: 1, fillColor: '#ffffff', fillOpacity: 1 }).bindTooltip(escape(name), { direction: 'top', className: 'trip-tip' }).addTo(layer))
    if (fitted.current !== map && lanes.length) {
      map.fitBounds(L.latLngBounds(lanes.flatMap((lane) => lane.geometry)), { padding: [16, 16] })
      fitted.current = map
    }
  }, [lanes, active, mapRef, layerRef, onPick])
  return (
    <div className="trip-map lg-tall">
      <div ref={holder} className="trip-map-canvas" />
      <Legend />
    </div>
  )
}

function NetworkPanel({ online, onAsk }: { online: boolean; onAsk: (text: string) => void }) {
  const [data, setData] = useState<NetworkResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await logisticsApi.network())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const pick = useCallback((id: string) => setActive((current) => (current === id ? null : id)), [])
  const s = data?.summary

  return (
    <>
      {loading && !data && <p className="trip-step">Reading the weather on 22 freight corridors…</p>}
      {error && <p className="trip-error">{error}</p>}
      {data && s && (
        <>
          <div className="cy-stats">
            <span style={{ borderTop: `3px solid ${s.affected ? '#ff9f43' : '#5fd39a'}` }}>
              <small>Corridors affected now</small>
              <b>
                {s.affected} of {s.total}
              </b>
              <em>{s.worst ? `worst: ${s.worst}` : 'all running clear'}</em>
            </span>
            <span>
              <small>Weather delay across the network</small>
              <b>{s.delay_min ? span(s.delay_min) : 'None'}</b>
              <em>{data.vehicle.toLowerCase()}, two drivers, leaving now</em>
            </span>
            <span>
              <small>Updated</small>
              <b>{hourOf(data.generated_at)}</b>
              <button className="lg-inline" onClick={load} disabled={loading || !online}>
                {loading ? 'Refreshing…' : 'Refresh'}
              </button>
            </span>
          </div>
          <NetworkMap lanes={data.lanes} active={active} onPick={pick} />
          <section className="trip-card">
            <h3>
              <Network size={15} /> Corridors, worst first
            </h3>
            <ul className="lg-lanes">
              {data.lanes.map((lane) => (
                <li key={lane.id} className={lane.id === active ? 'on' : ''} style={{ ['--c' as string]: levelColor(lane.level) }}>
                  <button onClick={() => pick(lane.id)}>
                    <b>{lane.name}</b>
                    <small>
                      {lane.distance_km.toLocaleString('en-IN')} km · {span(lane.duration_min)}
                      {lane.delay_min ? ` · weather delay ${span(lane.delay_min)}` : ' · no weather delay'}
                      {lane.warning_count ? ` · ${lane.warning_count} official warning${lane.warning_count > 1 ? 's' : ''}` : ''}
                    </small>
                    {lane.worst && (
                      <small className="bad">
                        {lane.worst.detail} around km {Math.round(lane.worst.km)}
                      </small>
                    )}
                  </button>
                  <div className="lg-outlook" aria-label="Delay if leaving later">
                    {lane.outlook.map((o) => (
                      <span key={o.hours} title={`Leaving in ${o.hours} h: ${o.risk.toLowerCase()} risk, ${o.delay_min} min delay`}>
                        <i style={{ background: riskColor(o.risk) }} />
                        <small>{o.hours ? `+${o.hours}h` : 'now'}</small>
                      </span>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <PdfButton url={reportUrl('network')} name="WeatherGPT-corridors.pdf" label="Download corridor status as PDF" />
          <button className="trip-ask" onClick={() => onAsk('Which freight corridors in India are disrupted by weather right now and over the next two days, and what should a transport planner do about each?')}>
            <MessageSquareText size={16} /> Ask WeatherGPT about the network
          </button>
        </>
      )}
    </>
  )
}

function SiteRow({ site, onRemove }: { site: Site; onRemove?: () => void }) {
  const [open, setOpen] = useState(false)
  const Icon = SITE_ICONS[site.kind]
  return (
    <li className={open ? 'open' : ''} style={{ ['--c' as string]: LEVEL_COLORS[site.level] }}>
      <button className="lg-site-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Icon size={16} />
        <div>
          <b>
            {site.name}
            {site.code ? ` (${site.code})` : ''}
          </b>
          <small>
            {[site.area, site.now.label, site.now.temp !== null ? `${Math.round(site.now.temp)} °C` : null, site.now.gust !== null ? `gusts ${Math.round(site.now.gust)} km/h` : null].filter(Boolean).join(' · ')}
          </small>
        </div>
        <div className="lg-days">
          {site.days.map((d) => (
            <span key={d.date} title={`${dayOf(d.date)}: ${d.status}${d.lost_hours ? `, ${d.lost_hours} h lost` : ''}`}>
              <i style={{ background: LEVEL_COLORS[d.level] }} />
              <small>{dayOf(d.date).slice(0, 2)}</small>
            </span>
          ))}
        </div>
        <em>{site.status}</em>
      </button>
      {open && (
        <div className="lg-site-body">
          {site.cyclone && (
            <p className="lg-note bad">
              Cyclone {site.cyclone.name ?? 'system'} passes within {site.cyclone.closest_km} km{site.cyclone.closest_time ? ` around ${when(site.cyclone.closest_time)}` : ''}.
            </p>
          )}
          {site.warnings.map((w, k) => (
            <p key={k} className="lg-note bad">
              {w.event} · {w.severity} · {w.issuer}
              {w.expires ? ` · until ${when(w.expires)}` : ''}
            </p>
          ))}
          <ul className="lg-daylist">
            {site.days.map((d) => (
              <li key={d.date} style={{ ['--c' as string]: LEVEL_COLORS[d.level] }}>
                <b>{dayOf(d.date)}</b>
                <div>
                  <span>
                    {d.status}
                    {d.lost_hours ? ` · ${d.lost_hours} h lost` : ''}
                    {d.slow_hours ? ` · ${d.slow_hours} h slow` : ''}
                  </span>
                  <small>
                    {[
                      `rain ${d.rain_mm} mm`,
                      `gusts ${d.gust_max} km/h`,
                      site.kind === 'port' && d.wave_max !== null ? `waves ${d.wave_max} m` : null,
                      site.kind !== 'port' && d.vis_min !== null ? `visibility ${d.vis_min >= 1000 ? `${(d.vis_min / 1000).toFixed(0)} km` : `${d.vis_min} m`}` : null,
                      site.kind === 'hub' && d.feels_max !== null ? `feels ${d.feels_max} °C` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                  {d.reasons.length > 0 && <small className="why">{d.reasons.join('; ')}</small>}
                </div>
              </li>
            ))}
          </ul>
          {onRemove && (
            <button className="add-btn" onClick={onRemove}>
              <Trash2 size={14} /> Remove this site
            </button>
          )}
        </div>
      )}
    </li>
  )
}

function SitesPanel({ place, online, onAsk }: { place: Place | null; online: boolean; onAsk: (text: string) => void }) {
  const [kind, setKind] = useState('all')
  const [data, setData] = useState<SitesResult | null>(null)
  const [mine, setMine] = useState(loadSites)
  const [own, setOwn] = useState<SitesResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<Place | null>(null)
  const [draftKind, setDraftKind] = useState('hub')
  const [showAll, setShowAll] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await logisticsApi.facilities(kind))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [kind])

  useEffect(() => {
    load()
  }, [load])

  const mineKey = JSON.stringify(mine)
  useEffect(() => {
    saveSites(mine)
    if (!mine.length) {
      setOwn(null)
      return
    }
    logisticsApi
      .sites(mine)
      .then(setOwn)
      .catch(() => setOwn(null))
  }, [mineKey])

  const rows = useMemo(() => (data ? (showAll ? data.sites : data.sites.filter((s) => s.level >= 1).concat(data.sites.filter((s) => s.level === 0)).slice(0, 14)) : []), [data, showAll])
  const s = data?.summary

  return (
    <>
      <div className="chips">
        {[
          ['all', 'All'],
          ['port', 'Ports'],
          ['airport', 'Cargo airports'],
          ['hub', 'Logistics hubs'],
        ].map(([id, label]) => (
          <button key={id} className={kind === id ? 'on' : ''} onClick={() => setKind(id)}>
            {label}
          </button>
        ))}
        <button onClick={load} disabled={loading || !online}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>
      {loading && !data && <p className="trip-step">Building the five-day outlook for ports, airports and hubs…</p>}
      {error && <p className="trip-error">{error}</p>}

      <section className="trip-card">
        <h3>
          <Warehouse size={15} /> My sites
        </h3>
        {own && (
          <ul className="lg-sites">
            {own.sites.map((site) => (
              <SiteRow key={site.id} site={site} onRemove={() => setMine(mine.filter((m) => m.ref !== site.id))} />
            ))}
          </ul>
        )}
        {own && mine.length > 0 && <PdfButton url={reportUrl('sites', { sites: mine })} name="WeatherGPT-sites.pdf" label="Download my sites as PDF" />}
        {!mine.length && <p className="lg-note">Add your own warehouses, plants or yards to get the same outlook for them.</p>}
        <div className="lg-add-site">
          <PlaceInput label="Add a site" value={draft} onChange={setDraft} current={place} />
          <select value={draftKind} onChange={(e) => setDraftKind(e.target.value)} aria-label="Site type">
            <option value="hub">Warehouse or yard</option>
            <option value="port">Port or jetty</option>
            <option value="airport">Airport</option>
          </select>
          <button
            className="add-btn"
            disabled={!draft || mine.length >= 30}
            onClick={() => {
              if (!draft) return
              setMine([...mine, { name: draft.name, lat: draft.lat, lon: draft.lon, kind: draftKind, ref: `${draftKind}:${draft.lat.toFixed(3)},${draft.lon.toFixed(3)}` }])
              setDraft(null)
            }}
          >
            <Plus size={14} /> Add
          </button>
        </div>
      </section>

      {data && s && (
        <>
          <div className="cy-stats">
            <span style={{ borderTop: `3px solid ${s.disrupted ? '#ff4d6d' : s.watch ? '#ffd166' : '#5fd39a'}` }}>
              <small>Disruption likely, next 2 days</small>
              <b>
                {s.disrupted} of {s.total}
              </b>
            </span>
            <span>
              <small>On watch</small>
              <b>{s.watch}</b>
            </span>
            <span>
              <small>Normal</small>
              <b>{s.normal}</b>
            </span>
          </div>
          <section className="trip-card">
            <h3>
              <Anchor size={15} /> Ports, cargo airports and hubs, worst first
            </h3>
            <ul className="lg-sites">
              {rows.map((site) => (
                <SiteRow key={site.id} site={site} />
              ))}
            </ul>
            {data.sites.length > 14 && (
              <button className="add-btn wide" onClick={() => setShowAll((v) => !v)}>
                {showAll ? 'Show fewer' : `Show all ${data.sites.length}`}
              </button>
            )}
            <p className="trip-source">
              {kind === 'all' ? Object.values(data.rules).join(' ') : data.rules[kind]} The dots are today and the next four days.
            </p>
          </section>
          <PdfButton url={reportUrl('facilities', undefined, { site_kind: kind })} name="WeatherGPT-facilities.pdf" label="Download this outlook as PDF" />
          <button className="trip-ask" onClick={() => onAsk('Which Indian ports, cargo airports and logistics hubs are likely to be disrupted by weather in the next five days, and when?')}>
            <MessageSquareText size={16} /> Ask WeatherGPT about facilities
          </button>
        </>
      )}
    </>
  )
}

function CodeBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="lg-code">
      <pre>{text}</pre>
      <button
        className="icon-btn"
        aria-label="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          } catch {
            setCopied(false)
          }
        }}
      >
        {copied ? <Check size={14} /> : <ClipboardCopy size={14} />}
      </button>
    </div>
  )
}

function ConnectPanel() {
  const shipment = `curl -X POST ${API_ORIGIN}/api/logistics/shipment \\
  -H "Content-Type: application/json" \\
  -d '{
    "ref": "LR-2041",
    "origin": {"name": "Pune"},
    "destination": {"name": "Hyderabad"},
    "mode": "road",
    "vehicle": "reefer",
    "cargo": "chilled",
    "crew": 1,
    "depart": "2026-10-06T21:00"
  }'`
  const fleet = `curl -X POST ${API_ORIGIN}/api/logistics/fleet \\
  -H "Content-Type: application/json" \\
  -d '{"shipments": [
    {"ref": "LR-2041", "origin": {"name": "Pune"}, "destination": {"name": "Hyderabad"}},
    {"ref": "BL-77", "origin": {"lat": 9.97, "lon": 76.27}, "destination": {"name": "Chennai"}, "mode": "sea"}
  ]}'`
  const answer = `"brief": {
  "verdict": "Go with caution",
  "reasons": ["Hazardous weather on part of the route"],
  "arrive": "2026-10-07T09:40:00+00:00",
  "arrive_latest": "2026-10-07T10:25:00+00:00",
  "weather_delay_min": 38,
  "hazards": [{"kind": "rain", "detail": "Heavy rain, 9.2 mm/h", "from_km": 212, "to_km": 268, "near": "Solapur"}],
  "cargo_status": "watch",
  "best_departure": {"depart": "2026-10-07T01:00:00+00:00", "why": "Dispatching 4 h later lowers the risk ..."}
}`
  return (
    <>
      <section className="trip-card">
        <h3>
          <Plug size={15} /> Use this inside your own software
        </h3>
        <p className="lg-note">
          Everything on these screens is available as a JSON API, so a transport management system, control tower or tracking app can call it for each trip it plans. Places can be names or coordinates, and your own reference comes back unchanged.
        </p>
        <table className="acc-table lg-endpoints">
          <tbody>
            {[
              ['POST', '/api/logistics/shipment', 'One shipment: verdict, weather-adjusted arrival, hazards by stretch, cargo exposure, best dispatch time'],
              ['POST', '/api/logistics/fleet', 'Up to 20 shipments in one call, each with a short result'],
              ['GET', '/api/logistics/network', 'Live status of the main freight corridors'],
              ['GET', '/api/logistics/facilities', 'Five-day outlook for ports, cargo airports and hubs'],
              ['POST', '/api/logistics/sites', 'The same outlook for your own warehouses and yards'],
              ['GET', '/api/logistics/options', 'Accepted modes, vehicles, cargo types, ports and hubs'],
            ].map(([verb, path, what]) => (
              <tr key={path}>
                <td>
                  <b>{verb}</b>
                </td>
                <td>
                  <code>{path}</code>
                  <small>{what}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <a className="add-btn" href={`${API_ORIGIN}/docs#/logistics`} target="_blank" rel="noreferrer">
          Open the full API reference
        </a>
      </section>
      <section className="trip-card">
        <h3>One shipment</h3>
        <CodeBlock text={shipment} />
        <p className="trip-source">The reply carries the full route detail plus a short summary under "brief":</p>
        <CodeBlock text={answer} />
      </section>
      <section className="trip-card">
        <h3>Many shipments</h3>
        <CodeBlock text={fleet} />
        <p className="trip-source">Call it when trips are planned and again every 30 minutes for trips on the road; results for the same route and hour are cached, so repeat calls are cheap. Dispatch times without a time zone are read as India Standard Time.</p>
      </section>
    </>
  )
}

export default function LogisticsView({ place, online, onAsk }: Props) {
  const [tab, setTab] = useState<Tab>('shipment')
  const [options, setOptions] = useState<LogiOptions>(FALLBACK)
  const [fleet, setFleetState] = useState(loadFleet)

  useEffect(() => {
    logisticsApi
      .options()
      .then(setOptions)
      .catch(() => undefined)
  }, [])

  const setFleet = (list: ShipmentRequest[]) => {
    setFleetState(list)
    saveFleet(list)
  }

  return (
    <div className="cy lg">
      <header className="trip-head cy-head">
        <h1>Logistics</h1>
        <p>Weather risk for freight by road, rail, air and sea: arrival times adjusted for the weather on the way, cargo exposure, the best time to dispatch, and the outlook for corridors, ports, airports and hubs.</p>
      </header>
      <nav className="lg-tabs" aria-label="Logistics sections">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>
            <Icon size={15} /> {label}
            {id === 'fleet' && fleet.length > 0 && <i>{fleet.length}</i>}
          </button>
        ))}
      </nav>
      {!online && <p className="trip-saved">You are offline. Logistics needs a live connection for routes and forecasts.</p>}
      {tab === 'shipment' && <ShipmentPanel place={place} options={options} onAsk={onAsk} onSave={(request) => setFleet([...fleet, request].slice(-options.limits.fleet))} />}
      {tab === 'fleet' && <FleetPanel fleet={fleet} setFleet={setFleet} options={options} online={online} />}
      {tab === 'network' && <NetworkPanel online={online} onAsk={onAsk} />}
      {tab === 'sites' && <SitesPanel place={place} online={online} onAsk={onAsk} />}
      {tab === 'connect' && <ConnectPanel />}
    </div>
  )
}
