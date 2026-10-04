const BASE = import.meta.env.VITE_API_BASE ?? ''

export type LogiMode = 'road' | 'rail' | 'air' | 'sea'

export interface LogiPlace {
  name?: string | null
  lat?: number
  lon?: number
  state?: string | null
}

export interface ShipmentRequest {
  ref?: string
  origin: LogiPlace
  destination: LogiPlace
  vias?: LogiPlace[]
  mode: LogiMode
  vehicle: string
  cargo: string
  crew: number
  depart?: string | null
}

export interface LogiReading {
  temp: number | null
  feels: number | null
  dew: number | null
  rh: number | null
  rain_mmh: number | null
  label: string
  gust: number | null
  visibility: number | null
  is_day: number | null
  wave: number | null
  swell: number | null
  elevation?: number | null
}

export interface LogiHazard {
  kind: string
  level: number
  detail: string
}

export interface LogiPoint {
  lat: number
  lon: number
  km: number
  eta: string
  level: number
  weather?: LogiReading | null
  hazards?: LogiHazard[]
  slow_pct?: number
  place?: string
}

export interface LogiSpan {
  kind: string
  level: number
  detail: string
  from_km: number
  to_km: number
  from_eta: string
  to_eta: string
  near: string | null
  severity: string
  advice: string
}

export interface LogiVerdict {
  code: 'go' | 'caution' | 'hold'
  label: string
  reasons: string[]
}

export interface LogiDeparture {
  depart: string
  arrive: string
  score: number
  risk: string
  delay_min: number
  night: number
  why?: string
}

export interface LogiCargo {
  id: string
  label: string
  status: 'ok' | 'watch' | 'risk'
  metrics: { label: string; value: string }[]
  notes: string[]
}

export interface LogiWarning {
  id: string
  event: string
  severity: string | null
  headline: string | null
  issuer: string | null
  expires: string | null
  from_km: number
  to_km: number
  active_on_arrival: boolean
}

export interface LogiCyclone {
  name: string | null
  closest_km: number
  route_km: number
  closest_time: string | null
  in_cone: boolean
}

export interface LogiRoute {
  summary: string
  source: string
  distance_km: number
  base_min: number
  drive_min: number
  rest_min: number
  delay_min: number
  delay_worst_min: number
  duration_min: number
  depart: string
  arrive: string
  arrive_latest: string
  risk: { score: number; label: string }
  verdict: LogiVerdict
  actions: string[]
  cargo: LogiCargo
  hazards: LogiSpan[]
  rests: { kind: 'break' | 'halt'; km: number; at: string; minutes: number; near?: string }[]
  warnings: LogiWarning[]
  cyclones: LogiCyclone[]
  departures: LogiDeparture[]
  best_departure: LogiDeparture | null
  night_share: number
  coverage: number
  geometry?: [number, number][]
  points: LogiPoint[]
  extra: Record<string, unknown>
  narrative: string[]
  breakdown: { kind: string; label: string; km: number; hours: number; level: number; severity: string; delay_min: number; worst: string }[]
  confidence: { score: number; label: string; lead_hours: number; note: string }
  stages?: LogiStage[]
  extremes?: { label: string; value: string; km: number; eta: string; place?: string }[]
  model_check?: { where: string; place?: string; km: number; date: string; score: number; label: string; rain_agreement: string; models: { name: string; rain_mm: number | null; tmax: number | null; gust: number | null }[] }[]
  other_crew?: { crew: number; arrive: string; duration_min: number; rest_min: number } | null
  top_departures?: LogiDeparture[]
}

export interface LogiStage {
  from?: string
  to?: string
  from_km: number
  to_km: number
  from_eta: string
  to_eta: string
  hours: number
  temp_min: number | null
  temp_max: number | null
  rain_mm: number
  rain_peak: number
  gust_max: number | null
  vis_min: number | null
  wave_max: number | null
  sky: string
  level: number
  slow_pct: number
  worst: string | null
  night: boolean
}

export interface ShipmentCardData {
  origin: string
  destination: string
  mode: string
  vehicle: string | null
  cargo: string
  verdict: LogiVerdict
  arrive: string
  distance_km: number
  delay_min: number
  delay_worst_min: number
  risk: string
  confidence: string
  report: string
}

export interface ShipmentResult {
  mode: LogiMode
  mode_label: string
  vehicle_label: string | null
  cargo_label: string
  crew: number
  origin: LogiPlace
  destination: LogiPlace
  generated_at: string
  routes: LogiRoute[]
  method: Record<string, string>
}

export interface FleetRow {
  ref: string | null
  ok: boolean
  error?: string
  origin?: LogiPlace
  destination?: LogiPlace
  mode_label?: string
  vehicle_label?: string | null
  cargo_label?: string
  distance_km?: number
  depart?: string
  arrive?: string
  arrive_latest?: string
  duration_min?: number
  delay_min?: number
  verdict?: LogiVerdict
  risk?: { score: number; label: string }
  cargo_status?: 'ok' | 'watch' | 'risk'
  worst?: { kind: string; detail: string; from_km: number; to_km: number; near: string | null } | null
  warnings?: number
  cyclones?: number
  best_departure?: LogiDeparture | null
  track?: LogiPoint[]
}

export interface FleetResult {
  generated_at: string
  shipments: FleetRow[]
  summary: { total: number; go: number; caution: number; hold: number; failed: number; delay_min: number }
}

export interface SiteDay {
  date: string
  level: number
  status: string
  lost_hours: number
  slow_hours: number
  hours: number
  rain_mm: number
  gust_max: number
  vis_min: number | null
  feels_max: number | null
  wave_max: number | null
  reasons: string[]
}

export interface Site {
  id: string
  kind: 'port' | 'airport' | 'hub'
  name: string
  area: string | null
  code: string | null
  lat: number
  lon: number
  level: number
  status: string
  now: { temp: number | null; feels: number | null; rain_mmh: number | null; gust: number | null; visibility: number | null; label: string }
  days: SiteDay[]
  warnings: { event: string; severity: string | null; headline: string | null; issuer: string | null; expires: string | null }[]
  cyclone: { name: string | null; closest_km: number; closest_time: string | null } | null
}

export interface SitesResult {
  generated_at: string
  sites: Site[]
  summary: { total: number; normal: number; watch: number; disrupted: number }
  rules: Record<string, string>
}

export interface Lane {
  id: string
  name: string
  from: { name: string; lat: number; lon: number }
  to: { name: string; lat: number; lon: number }
  via: string
  distance_km: number
  base_min: number
  duration_min: number
  delay_min: number
  delay_worst_min: number
  risk: { score: number; label: string }
  level: number
  worst: { kind: string; detail: string; km: number } | null
  warnings: { event: string; severity: string | null }[]
  warning_count: number
  outlook: { depart: string; hours: number; delay_min: number; score: number; risk: string }[]
  segments: { lat: number; lon: number; level: number }[]
  geometry: [number, number][]
}

export interface NetworkResult {
  generated_at: string
  lanes: Lane[]
  vehicle: string
  summary: { total: number; clear: number; affected: number; delay_min: number; worst: string | null }
}

export interface LogiOptions {
  modes: { id: LogiMode; label: string }[]
  vehicles: { id: string; label: string }[]
  cargo: { id: string; label: string }[]
  ports: { id: string; name: string; state: string; lat: number; lon: number }[]
  hubs: { id: string; name: string; city: string; lat: number; lon: number }[]
  limits: { fleet: number; sites: number; vias: number }
}

async function send<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const logisticsApi = {
  options: () => send<LogiOptions>('/api/logistics/options'),
  shipment: (request: ShipmentRequest) => send<ShipmentResult>('/api/logistics/shipment', request),
  fleet: (shipments: ShipmentRequest[]) => send<FleetResult>('/api/logistics/fleet', { shipments }),
  facilities: (kind: string) => send<SitesResult>(`/api/logistics/facilities?kind=${kind}`),
  sites: (sites: (LogiPlace & { kind: string; ref?: string })[]) => send<SitesResult>('/api/logistics/sites', { sites }),
  network: () => send<NetworkResult>('/api/logistics/network'),
  analysis: (request: ShipmentRequest, route: number) => send<{ text: string; model: string | null }>('/api/logistics/analysis', { ...request, route }),
}

export const API_ORIGIN = BASE || (typeof window === 'undefined' ? '' : window.location.origin)

function pack(value: unknown) {
  const bytes = new TextEncoder().encode(JSON.stringify(value))
  let binary = ''
  bytes.forEach((b) => (binary += String.fromCharCode(b)))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function reportUrl(kind: 'shipment' | 'fleet' | 'network' | 'facilities' | 'sites', body?: unknown, extra: Record<string, string | number> = {}) {
  const params = new URLSearchParams({ kind, ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, String(v)])) })
  if (body !== undefined) params.set('q', pack(body))
  return `${API_ORIGIN}/api/logistics/report.pdf?${params.toString()}`
}

export const LEVEL_COLORS = ['#5fd39a', '#ffd166', '#ff9f43', '#ff4d6d']
export const levelColor = (level: number) => LEVEL_COLORS[Math.max(0, Math.min(3, Math.floor(level)))]
export const riskColor = (label: string) => LEVEL_COLORS[Math.max(0, ['Low', 'Moderate', 'High', 'Severe'].indexOf(label))]
export const VERDICT_COLORS: Record<LogiVerdict['code'], string> = { go: '#5fd39a', caution: '#ffd166', hold: '#ff4d6d' }

export function span(minutes: number) {
  const total = Math.max(0, Math.round(minutes))
  const days = Math.floor(total / 1440)
  const hours = Math.floor((total % 1440) / 60)
  const mins = total % 60
  if (days) return `${days} d ${hours} h`
  if (hours) return mins ? `${hours} h ${mins} min` : `${hours} h`
  return `${mins} min`
}

export const when = (iso: string) => new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
export const hourOf = (iso: string) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
export const dayOf = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' })

const FLEET_KEY = 'weathergpt:fleet'
const SITES_KEY = 'weathergpt:sites'

function read<T>(key: string): T[] {
  try {
    const list = JSON.parse(localStorage.getItem(key) ?? '[]') as T[]
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

function write(key: string, list: unknown[]) {
  try {
    localStorage.setItem(key, JSON.stringify(list))
  } catch {
    return
  }
}

export const loadFleet = () => read<ShipmentRequest>(FLEET_KEY)
export const saveFleet = (list: ShipmentRequest[]) => write(FLEET_KEY, list)
export const loadSites = () => read<LogiPlace & { kind: string; ref: string }>(SITES_KEY)
export const saveSites = (list: (LogiPlace & { kind: string; ref: string })[]) => write(SITES_KEY, list)

const MODE_WORDS: Record<string, LogiMode> = { road: 'road', truck: 'road', rail: 'rail', train: 'rail', air: 'air', flight: 'air', sea: 'sea', ship: 'sea' }

export function parseFleetLines(text: string, vehicles: string[], cargo: string[]): { rows: ShipmentRequest[]; skipped: number } {
  const rows: ShipmentRequest[] = []
  let skipped = 0
  for (const line of text.split(/\r?\n/)) {
    const cells = line.split(/[,;\t]/).map((c) => c.trim())
    if (cells.every((c) => !c)) continue
    const [ref, from, to, mode, vehicle, load, depart] = cells
    if (!from || !to || /^(ref|reference|id)$/i.test(ref ?? '')) {
      skipped += from && to ? 0 : 1
      continue
    }
    rows.push({
      ref: ref || `${from} → ${to}`,
      origin: { name: from },
      destination: { name: to },
      mode: MODE_WORDS[(mode ?? '').toLowerCase()] ?? 'road',
      vehicle: vehicles.includes((vehicle ?? '').toLowerCase()) ? vehicle.toLowerCase() : 'hcv',
      cargo: cargo.includes((load ?? '').toLowerCase()) ? load.toLowerCase() : 'general',
      crew: 1,
      depart: depart && !Number.isNaN(Date.parse(depart)) ? depart : null,
    })
  }
  return { rows, skipped }
}
