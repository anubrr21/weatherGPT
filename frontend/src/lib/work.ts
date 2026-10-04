import type { CropEntry, Role } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface FarmTask {
  task: 'spray' | 'irrigate' | 'fertiliser' | 'harvest' | 'hazard'
  status: 'good' | 'avoid' | 'caution'
  text: string
  detail: string
}

export interface FarmDay {
  date: string
  tmax: number | null
  tmin: number | null
  rain_mm: number
  rain_prob: number | null
  gust: number
  rh: number | null
  sunshine_h: number
  wet_hours: number
  tasks: FarmTask[]
  spray_windows: { start: string; end: string; hours: number }[]
}

export interface FarmDisease {
  id: string
  name: string
  crops: string[]
  peak: number
  peak_label: string
  risky_days: string[]
  days: { date: string; level: number; past: boolean }[]
  why: string
  watch_for: string
  source: string
}

export interface FarmWorkspace {
  generated: string
  today: string
  crops: { crop: string; stage: string | null; kc: number }[]
  plan: FarmDay[]
  spray: { rules: string; main_blocker: string | null; count: number }
  water: {
    crop: string | null
    stage: string | null
    kc: number
    days: { date: string; need_mm: number; rain_mm: number; effective_mm: number; deficit_mm: number; irrigate: boolean }[]
    need_7d_mm: number
    rain_7d_mm: number
    effective_7d_mm: number
    rain_last_7d_mm: number
    rainy_days_last_7d: number
    irrigations: string[]
    method: string
  }
  diseases: FarmDisease[]
  soil: {
    now: { temp_surface: number; temp_6cm: number; temp_18cm: number; moisture_top: number; moisture_root: number; moisture_deep: number } | null
    days: { date: string; past: boolean; temp_6cm: number; temp_18cm: number; moisture_top: number; moisture_root: number; moisture_deep: number }[]
    seed_depth_temp: number | null
    sowing: { crop: string; soil_temp: number; verdict: 'good' | 'caution' | 'avoid'; text: string }[]
  }
  livestock: { date: string; thi: number; level: 'none' | 'mild' | 'moderate' | 'severe' }[]
  warnings?: { event: string | null; severity: string | null; headline: string | null; expires: string | null }[]
  note: string
  source: string
}

async function get<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const response = await fetch(`${BASE}${path}?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

export type Boat = 'small' | 'motor' | 'trawler'
export type SeaVerdict = 'GO' | 'CAUTION' | 'NO-GO'

export interface SeaDay {
  date: string
  wave_max: number
  swell_max: number
  gust_max: number
  wind_max: number
  rain_mm: number
  thunder: boolean
  sunrise: string | null
  sunset: string | null
  tides: { type: 'high' | 'low'; time: string; height_m: number }[]
  boats: Record<Boat, { verdict: SeaVerdict; go_hours: number; windows: { start: string; end: string; hours: number }[] }>
}

export interface SeaWorkspace {
  available: boolean
  reason?: string
  generated: string
  sea_point: { lat: number; lon: number }
  boats: Record<Boat, { label: string; caution: [number, number]; nogo: [number, number] }>
  now: {
    time: string
    wave: number | null
    wave_dir: string | null
    wave_period: number | null
    wind_wave: number | null
    swell: number | null
    swell_dir: string | null
    swell_period: number | null
    current_kmh: number | null
    current_dir: string | null
    sst: number | null
    wind: number | null
    gust: number | null
    wind_dir: string | null
    visibility: number | null
    thunder: boolean
    verdicts: Record<Boat, SeaVerdict>
    reasons: Record<Boat, string[]>
  }
  official: { event: string | null; severity: string | null; headline: string | null; expires: string | null; issuer: string | null }[]
  hours: { time: string; wave: number | null; swell: number | null; wind: number | null; gust: number | null; wind_dir: string | null; tide: number | null; thunder: boolean; is_day: number; verdicts: Record<Boat, SeaVerdict> }[]
  days: SeaDay[]
  next_tides: { type: 'high' | 'low'; time: string; height_m: number }[]
  moon: { age_days: number; illumination: number; phase: string; spring_tide: boolean }
  rules: string
  source: string
}

export type FlightCategory = 'VFR' | 'MVFR' | 'IFR' | 'LIFR'

export interface TafPeriod {
  from: string
  to: string
  change: string | null
  probability: number | null
  wind_dir: number | string | null
  wind_kt: number | null
  gust_kt: number | null
  visibility_km: number | null
  ceiling_ft: number | null
  weather: string
  clouds: { cover: string | null; base_ft: number | null; type: string | null }[]
  category: FlightCategory
  thunder: boolean
}

export interface AirportWeather {
  icao: string
  iata: string | null
  name: string
  city: string | null
  lat: number
  lon: number
  elevation_ft: number | null
  metar: {
    raw: string | null
    observed: string | null
    decoded: { wind?: string; visibility?: string; clouds?: string[]; weather?: string[]; temp_dew?: string; qnh?: string; trend?: string; hazards?: string[] }
    wind_dir: number | string | null
    wind_kt: number | null
    gust_kt: number | null
    temp_c: number | null
    dewpoint_c: number | null
    qnh_hpa: number | null
    visibility_km: number | null
    ceiling_ft: number | null
    category: FlightCategory | null
  } | null
  taf: { raw: string | null; issued: string | null; periods: TafPeriod[] } | null
  runways?: { runway: string; heading: number; length_ft: number | null; headwind_kt: number; crosswind_kt: number; gust_crosswind_kt: number; tailwind: boolean; favoured: boolean }[]
  density?: { elevation_ft: number; pressure_altitude_ft: number; density_altitude_ft: number; isa_deviation_c: number } | null
}

export interface AviationWorkspace {
  available: boolean
  reason?: string
  generated: string
  airport: AirportWeather
  distance_km: number | null
  alternates: { icao: string; iata: string | null; name: string; city: string | null; km: number; category: FlightCategory | null; raw: string | null; wind: string | null; visibility_km: number | null; ceiling_ft: number | null }[]
  aloft: {
    frames: { time: string; levels: { level: string; hpa: number; altitude_ft: number | null; wind_dir: number | null; wind_kt: number | null; temp_c: number | null }[]; freezing_level_ft: number | null; cape: number | null }[]
    strongest: { level: string; wind_kt: number | null } | null
    max_cape: number
  }
  sigmets: { fir: string; fir_name: string; hazard: string; qualifier: string | null; from: string; to: string; top_ft: number | null; raw: string | null; near: boolean }[]
  hazards: { level: 'high' | 'moderate'; title: string; detail: string }[]
  choices: { icao: string; iata: string | null; name: string; km: number | null; reports: boolean }[]
  source: string
}

export interface CityWorkspace {
  generated: string
  today: string
  now: {
    temp: number
    heat_index: number
    heat_band: string
    uv: number | null
    rain_in_min: number | null
    rain_next_3h_mm: number
    naqi: number | null
    air_band: string | null
    dominant: string | null
    pm25: number | null
    pm10: number | null
    air_advice: string | null
  }
  commute: {
    morning_hour: number
    evening_hour: number
    trips: { label: string; date: string; hour: number; rain_mm: number; rain_prob: number; heat_index: number; thunder: boolean; visibility_km: number | null; tips: string[]; better_time: string | null }[]
  }
  flooding: { date: string; max_1h_mm: number; max_3h_mm: number; total_mm: number; level: 'none' | 'low' | 'moderate' | 'high'; peak_time: string | null }[]
  heat: { date: string; peak: number; peak_time: string; band: string; danger_from: string | null; danger_to: string | null; uv_max: number; tmax: number; tmin: number }[]
  air: { date: string; pm25_mean: number; pm25_max: number; worst_time: string; cleanest_time: string; band: string | null }[]
  outdoor: { start: string; end: string; hours: number; heat_index: number; pm25: number }[]
  hours: { time: string; heat_index: number; rain: number; rain_prob: number; pm25: number | null; uv: number | null; thunder: boolean; is_day: number }[]
  warnings?: { event: string | null; severity: string | null; headline: string | null; expires: string | null }[]
  rules: string
  source: string
}

export interface CommandTown {
  name: string
  kind: string
  lat: number
  lon: number
  population: number | null
  km: number
  direction: string
  rain_past_24h: number
  rain_next_24h: number
  rain_next_72h: number
  rain_band: string
  max_hourly_mm: number
  max_hourly_time: string | null
  gust_max: number
  heat_index_max: number | null
  thunder_hours: number
  score: number
  warnings: { event: string; severity: string | null }[]
}

export interface CommandWorkspace {
  available: boolean
  reason?: string
  generated: string
  radius_km: number
  centre: { lat: number; lon: number; name: string }
  summary: {
    towns: number
    flagged: number
    population_flagged: number
    population_scanned: number
    heavy_towns: number
    warned_towns: number
    thunder_towns: number
    wettest: CommandTown
    wettest_past: CommandTown
    windiest: CommandTown
    hottest: CommandTown | null
    area_rain_next_24h: number
    area_rain_past_24h: number
  }
  towns: CommandTown[]
  official: { id: string; event: string; severity: string | null; headline: string | null; issuer: string; expires: string | null; areas: string[]; towns: string[]; rings: [number, number][][] }[]
  storms: { name: string | null; now: { grade: { label: string } | null }; impact: { distance_now_km: number; direction_now: string; closest: { km: number; time: string } | null } }[]
  sitrep: string
  rules: string
  source: string
}

export interface ResearchWorkspace {
  generated: string
  exports: string[]
  models: {
    models: Record<string, string>
    days: (Record<string, { tmax: number | null; tmin: number | null; rain: number | null; gust: number | null }> & { date: string; spread_tmax: number; spread_rain: number })[]
    stats: { mean_tmax_spread?: number; max_tmax_spread?: number; max_tmax_spread_date?: string; max_rain_spread?: number; max_rain_spread_date?: string; rain_totals?: Record<string, number>; wettest_model?: string; driest_model?: string }
  } | null
  climate: {
    period: string
    source: string
    annual: { year: number; mean_temp: number; hot_days_over_40: number; rain_total: number }[]
    annual_temp_trend_c_per_decade: number | null
    annual_rain_trend_mm_per_decade: number | null
    month: number
    month_normal_1991_2020: { mean_temp: number; rain_total: number } | null
    stats: { first_decade?: string; last_decade?: string; temp_change_c?: number; rain_change_mm?: number; hot_days_first?: number; hot_days_last?: number; warmest_year?: number; wettest_year?: number; driest_year?: number }
  } | null
  stations: {
    station: string
    name: string | null
    lat: number
    lon: number
    km: number
    kind: string
    count: number
    latest: { time: string; temp_c: number | null; dewpoint_c: number | null; wind_kmh: number | null; pressure_hpa: number | null; weather: string | null; raw: string | null }
    series: { time: string; temp_c: number | null }[]
  }[]
  source: string
}

export const exportUrl = (kind: string, lat: number, lon: number) => `${BASE}/api/work/data/export?kind=${kind}&lat=${lat}&lon=${lon}`
export const apiDocsUrl = `${BASE}/docs`

export const workApi = {
  command: (lat: number, lon: number, radius: number) => get<CommandWorkspace>('/api/work/command', { lat, lon, radius_km: radius }),
  research: (lat: number, lon: number) => get<ResearchWorkspace>('/api/work/data', { lat, lon }),
  city: (lat: number, lon: number, am: number, pm: number) => get<CityWorkspace>('/api/work/city', { lat, lon, am, pm }),
  aviation: (lat: number, lon: number, icao?: string | null) => get<AviationWorkspace>('/api/work/aviation', icao ? { lat, lon, icao } : { lat, lon }),
  sea: (lat: number, lon: number) => get<SeaWorkspace>('/api/work/sea', { lat, lon }),
  farm: (lat: number, lon: number, crops: CropEntry[]) =>
    get<FarmWorkspace>('/api/work/farm', { lat, lon, crops: crops.map((c) => `${c.name}${c.stage ? `:${c.stage}` : ''}`).join(',') }),
}

export const WORK_TABS: Partial<Record<Role, { label: string }>> = {
  farmer: { label: 'Farm' },
  fisher: { label: 'Sea' },
  aviation: { label: 'Aviation' },
  urban: { label: 'City' },
  disaster_manager: { label: 'Command' },
  researcher: { label: 'Data' },
  logistics: { label: 'Logistics' },
}

export const dayName = (date: string, today: string) => {
  if (date === today) return 'Today'
  const d = new Date(`${date}T12:00:00`)
  const t = new Date(`${today}T12:00:00`)
  if (Math.round((d.getTime() - t.getTime()) / 86400000) === 1) return 'Tomorrow'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export const shortDay = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })
