const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface Strike {
  t: number
  lat: number
  lon: number
  km: number
  stations: number
}

export interface OfficialArea {
  id: string
  event: string | null
  severity: string | null
  headline: string | null
  instruction: string | null
  issuer: string | null
  areas: string[]
  effective: string | null
  expires: string | null
  localized: { language: string | null; headline: string | null }[]
  rings: [number, number][][]
}

export interface Motion {
  speed_kmh: number
  heading: string
  closing_kmh: number
  eta_min: number | null
  centre: { lat: number; lon: number; km: number }
}

export interface LightningLive {
  now: string
  radius_km: number
  minutes: number
  strikes: Strike[]
  count: number
  rings_30min: Record<string, number>
  nearest: { km: number; direction: string; minutes_ago: number } | null
  last_within_10km_min: number | null
  motion: Motion | null
  feed: { connected: boolean; listening_min: number; last_message_s: number | null; region_strikes: number; source: string }
  official: OfficialArea[]
  official_here: string[]
}

export interface RiskCell {
  lat: number
  lon: number
  score: number
  cape: number
  time: string | null
}

export interface OutlookHour {
  time: string
  score: number
  code: number
  cape: number
  lifted: number | null
  rain_prob: number | null
  rain: number | null
  gust: number | null
}

export interface LightningRisk {
  grid: { step: number; hours: number; cells: RiskCell[]; source: string }
  outlook: { hours: OutlookHour[]; next_storm: string | null; peak: number }
}

async function get<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const response = await fetch(`${BASE}${path}?${new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))}`)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

export const lightningApi = {
  live: (lat: number, lon: number) => get<LightningLive>('/api/lightning/live', { lat, lon, radius_km: 300, minutes: 60 }),
  risk: (lat: number, lon: number) => get<LightningRisk>('/api/lightning/risk', { lat, lon }),
}

export const RISK_COLORS = ['transparent', '#ffd166', '#ff8c42', '#ff3d6e']
export const RISK_LABELS = ['Unlikely', 'Possible', 'Likely', 'Likely, strong']

export function ageColor(minutes: number) {
  if (minutes <= 5) return '#ffffff'
  if (minutes <= 15) return '#ffe066'
  if (minutes <= 30) return '#ff9f43'
  return '#ff4d6d'
}

export const severityColor = (severity: string | null) =>
  severity === 'Extreme' ? '#ff4d6d' : severity === 'Severe' ? '#ff8a4c' : severity === 'Moderate' ? '#ffc857' : '#9fd1ff'

export function areaCentre(area: OfficialArea): [number, number] | null {
  const points = area.rings.flat()
  if (!points.length) return null
  return [points.reduce((s, p) => s + p[1], 0) / points.length, points.reduce((s, p) => s + p[0], 0) / points.length]
}

export function distanceKm(a: [number, number], b: [number, number]) {
  const p1 = (a[0] * Math.PI) / 180
  const p2 = (b[0] * Math.PI) / 180
  const dp = p2 - p1
  const dl = ((b[1] - a[1]) * Math.PI) / 180
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)))
}

export const localHeadline = (area: OfficialArea, language: string) =>
  area.localized.find((l) => {
    const code = (l.language ?? '').toLowerCase().slice(0, 2)
    return code === language || (language === 'te' && code === 'tl')
  })?.headline ?? null
