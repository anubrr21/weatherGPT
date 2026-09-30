const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface Grade {
  code: string
  label: string
  level: number
  kt: number
  kmh: number
}

export interface Fix {
  time: string
  lat: number
  lon: number
  kt: number | null
  grade: Grade | null
  forecast: boolean
  gust_kmh?: number | null
  pressure?: number | null
  status?: string | null
  gale_radius_km?: Record<string, number>
  population_gale?: number
}

export interface Approach {
  km: number
  lat: number
  lon: number
  time: string
  kt: number | null
  grade: Grade | null
  forecast: boolean
  direction: string
}

export interface Impact {
  distance_now_km: number
  direction_now: string
  closest: Approach | null
  hours_to_closest: number | null
  in_cone: boolean
  wind_zone: { kmh: number; time: string } | null
  first_gale: string | null
  stage: { code: string; label: string; severity: string; lead_hours: number } | null
}

type Geometry = { type: 'Polygon'; coordinates: number[][][] } | { type: 'MultiPolygon'; coordinates: number[][][][] }

export interface LiveStorm {
  id: string
  name: string | null
  source: string
  alert_level: string | null
  current: boolean
  countries: string[]
  start: string | null
  end: string | null
  issued: string | null
  now: Fix & { grade: Grade | null }
  peak: Grade | null
  track: Fix[]
  shapes: { cone: Geometry | null; swath: Geometry | null; radii: { time: string; kmh: number; geometry: Geometry }[] }
  surge: { max_m: number; max_rain_mm: number | null; max_wind_ms: number | null; source: string; issued: string } | null
  images: Record<string, string>
  report: string | null
  impact?: Impact
}

export interface StormSummary {
  sid: string
  name: string | null
  season: number
  basin: string
  start: string
  end: string
  peak: Grade | null
  provisional: boolean
  landfalls: { time: string; lat: number; lon: number }[]
  sources: string[]
}

export interface Outlook {
  jtwc: { available: boolean; issuer?: string; valid?: string | null; valid_until?: string | null; sections?: Record<string, string | null>; quiet?: boolean; url?: string; error?: string }
  imd: {
    available: boolean
    page?: string
    special?: { url: string; nil: boolean; issued: string | null; text: string; error?: string }
    routine?: { url: string; nil: boolean; issued: string | null; text: string; error?: string }
    error?: string
  }
}

export interface OfficialAlert {
  id: string
  event?: string
  severity: string
  headline: string
  instruction?: string
  expires?: string
  issuer?: string
}

export interface CycloneLive {
  fetched: string
  outlook: Outlook
  active: LiveStorm[]
  recent: LiveStorm[]
  season: StormSummary[]
  climatology: { per_month: Record<string, number[]>; seasons: number; since: number | null; note: string }
  official?: OfficialAlert[]
  nearest_landfall_km?: number | null
}

export interface HistoryStorm extends StormSummary {
  closest_km: number
  closest_time: string
  at_closest: Grade | null
  direction: string
  landfall_km: number | null
}

export interface CycloneHistory {
  available: boolean
  radius_km: number
  since: number
  until: number
  count: number
  cyclonic_storms: number
  severe_or_worse: number
  landfalls: number
  return_period_years: number | null
  by_month: number[]
  by_decade: Record<string, number>
  storms: HistoryStorm[]
  strongest: string[]
  tracks: Record<string, [number, number, number | null][]>
  source: string
}

export interface LocalWinds {
  hours: { time: string; wind: number | null; gust: number | null; rain: number | null; pressure: number | null }[]
  max_gust: { kmh: number; time: string } | null
  rain_72h_mm: number
  min_pressure: { hpa: number; time: string } | null
  source: string
}

export interface Shelter {
  osm: string
  kind: 'cyclone' | 'relief' | 'assembly' | 'public'
  name: string | null
  label: string
  lat: number
  lon: number
  km: number
  capacity?: string
  operator?: string
}

export interface Shelters {
  radius_km: number
  designated: Shelter[]
  public: Shelter[]
  indexed: boolean
  note: string
  source: string
  helplines: { number: string; label: string }[]
}

async function get<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const response = await fetch(`${BASE}${path}?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

export const cycloneApi = {
  live: (lat: number, lon: number) => get<CycloneLive>('/api/cyclones/live', { lat, lon }),
  history: (lat: number, lon: number, radius: number) => get<CycloneHistory>('/api/cyclones/history', { lat, lon, radius_km: radius }),
  local: (lat: number, lon: number) => get<LocalWinds>('/api/cyclones/local', { lat, lon }),
  shelters: (lat: number, lon: number) => get<Shelters>('/api/cyclones/shelters', { lat, lon, radius_km: 30 }),
  storm: (sid: string) => fetch(`${BASE}/api/cyclones/storm/${encodeURIComponent(sid)}`).then((r) => r.json() as Promise<StormSummary & { track: (Fix & { land: boolean })[] }>),
}

export const GRADE_COLORS = ['#8fa3bf', '#6fb7ff', '#3ddcc4', '#ffd166', '#ff9f43', '#ff6b4a', '#e8365d', '#b42bd6']

export const gradeColor = (level: number | null | undefined) => GRADE_COLORS[Math.max(0, Math.min(7, level ?? 0))]

export const GRADE_TABLE = [
  { code: 'D', label: 'Depression', kt: '17–27', kmh: '31–49' },
  { code: 'DD', label: 'Deep Depression', kt: '28–33', kmh: '50–61' },
  { code: 'CS', label: 'Cyclonic Storm', kt: '34–47', kmh: '62–88' },
  { code: 'SCS', label: 'Severe Cyclonic Storm', kt: '48–63', kmh: '89–117' },
  { code: 'VSCS', label: 'Very Severe Cyclonic Storm', kt: '64–89', kmh: '118–166' },
  { code: 'ESCS', label: 'Extremely Severe Cyclonic Storm', kt: '90–119', kmh: '167–221' },
  { code: 'SuCS', label: 'Super Cyclonic Storm', kt: '120+', kmh: '222+' },
]

export const STAGES = [
  { code: 'watch', label: 'Pre-cyclone watch', when: 'About 72 h before adverse weather', what: 'A cyclonic disturbance may affect the coast. Check shelters, stock water, food, medicines and documents.' },
  { code: 'alert', label: 'Cyclone alert', when: 'About 48 h before', what: 'Fishermen called back, ports warned. Secure boats and loose objects, charge phones and power banks.' },
  { code: 'warning', label: 'Cyclone warning', when: 'About 24 h before', what: 'Landfall point, wind and surge given. Evacuate low-lying and kutcha houses to shelters when told to.' },
  { code: 'post_landfall', label: 'Post-landfall outlook', when: 'About 12 h before landfall', what: 'Inland impact of wind and heavy rain. Stay indoors until the all-clear, beware of fallen wires and flooding.' },
]

export const ist = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const stormLabel = (name: string | null, start: string | null | undefined, grade?: Grade | null) =>
  name ?? `${grade?.label ?? 'Depression'}${start ? ` of ${new Date(start).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })}` : ''}`
