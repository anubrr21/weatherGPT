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

export const workApi = {
  sea: (lat: number, lon: number) => get<SeaWorkspace>('/api/work/sea', { lat, lon }),
  farm: (lat: number, lon: number, crops: CropEntry[]) =>
    get<FarmWorkspace>('/api/work/farm', { lat, lon, crops: crops.map((c) => `${c.name}${c.stage ? `:${c.stage}` : ''}`).join(',') }),
}

export const WORK_TABS: Partial<Record<Role, { label: string }>> = {
  farmer: { label: 'Farm' },
  fisher: { label: 'Sea' },
}

export const dayName = (date: string, today: string) => {
  if (date === today) return 'Today'
  const d = new Date(`${date}T12:00:00`)
  const t = new Date(`${today}T12:00:00`)
  if (Math.round((d.getTime() - t.getTime()) / 86400000) === 1) return 'Tomorrow'
  return d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
}

export const shortDay = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })
