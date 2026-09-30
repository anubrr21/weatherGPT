import type { Place } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const LAST_KEY = 'weathergpt:last-trip'

export type TripMode = 'car' | 'bike' | 'bus' | 'train' | 'flight' | 'trek'

export interface TripWeather {
  temp: number | null
  feels: number | null
  rain_mmh: number | null
  rain_prob: number | null
  code: number | null
  label: string
  gust: number | null
  visibility: number | null
  is_day: number | null
  elevation: number | null
}

export interface TripHazard {
  kind: string
  level: number
  detail: string
}

export interface TripPoint {
  i: number
  lat: number
  lon: number
  km: number
  eta: string
  place?: string
  weather: TripWeather | null
  hazards: TripHazard[]
  level: number
}

export interface TripSpan {
  kind: string
  level: number
  severity: string
  detail: string
  advice: string
  from_km: number
  to_km: number
  from_eta: string
  to_eta: string
  near: string | null
}

export interface TripDeparture {
  depart: string
  score: number
  risk: string
  night: number
}

export interface Airport {
  icao: string
  iata: string | null
  name: string
  city: string | null
  lat: number
  lon: number
  km_from_origin?: number
  km_from_destination?: number
  metar?: { available: boolean; raw_metar?: string; raw_taf?: string; flight_category?: string; temp_c?: number; wind_kt?: number; visibility?: string | number } | null
}

export interface Station {
  name: string
  lat: number
  lon: number
  km_from_origin?: number
  km_from_destination?: number
}

export interface RestOption {
  name: string
  kind: 'services' | 'rest_area' | 'fuel' | 'restaurant' | 'fast_food' | 'cafe' | 'hotel' | 'motel' | 'guest_house'
  lat: number
  lon: number
  detour_km: number
  brand: string | null
  cuisine: string | null
  stars: string | null
  opening_hours: string | null
  phone: string | null
  website: string | null
  osm: string
  google?: { rating: number; count: number; url: string | null; name: string | null }
}

export interface AlongPlace extends RestOption {
  km: number
  after_min: number
  eta: string
  near_break: boolean
  after_overnight: boolean
}

export interface StopsAlong {
  places: AlongPlace[]
  total_found?: number
  counts?: Record<string, number>
  radius_km?: number
  partial?: boolean
  ratings?: 'google' | null
  error?: string
}

export interface RestStop {
  reason: 'break' | 'overnight'
  after_min: number
  km: number
  lat: number
  lon: number
  eta: string
  near: string | null
  weather: TripWeather | null
  wait_out: { kind: string; severity: string; detail: string; near: string | null } | null
  options: RestOption[]
  after_overnight: boolean
  lodging_nearby: (RestOption & { km: number; near: string | null }) | null
  error?: string
}

export interface TripVia {
  name: string
  district?: string | null
  state?: string | null
  lat: number
  lon: number
  km: number
  eta: string
}

export interface TripRoute {
  summary: string
  source: string
  distance_km: number
  duration_min: number
  depart: string
  arrive: string
  geometry: [number, number][]
  points: TripPoint[]
  vias?: TripVia[]
  hazards: TripSpan[]
  rest_stops?: RestStop[] | null
  stops_along?: StopsAlong | null
  risk: { score: number; label: string }
  night_share: number
  departures: TripDeparture[]
  best_departure: (TripDeparture & { why: string }) | null
  alerts: { id: string; event?: string; severity: string; headline: string; near?: string; km?: number; expires?: string }[]
  extra: {
    from_airport?: Airport
    to_airport?: Airport
    from_station?: Station
    to_station?: Station
    via_airports?: Airport[]
    via_stations?: Station[]
    legs?: number
    layover_min?: number
    winds?: { tailwind_kmh: number; adjusted_minutes: number; samples: number }
    great_circle_km?: number
  }
}

export interface TripResult {
  mode: TripMode
  mode_label: string
  origin: Place
  destination: Place
  vias?: Place[]
  generated_at: string
  routes: TripRoute[]
  briefs: Record<string, unknown>[]
}

export const MODES: { id: TripMode; label: string }[] = [
  { id: 'car', label: 'Car' },
  { id: 'bike', label: 'Two-wheeler' },
  { id: 'bus', label: 'Bus' },
  { id: 'train', label: 'Train' },
  { id: 'flight', label: 'Flight' },
  { id: 'trek', label: 'Trek' },
]

export const LEVEL_COLORS = ['#3ddc97', '#ffd166', '#ff8c42', '#ff4d6d']

export const levelColor = (level: number) => LEVEL_COLORS[Math.min(3, Math.max(0, Math.floor(level)))]

export const MAX_VIAS = 8

const placeBody = (p: Place) => ({ name: p.name, lat: p.lat, lon: p.lon, district: p.district ?? null, state: p.state ?? null })

export async function planTrip(origin: Place, destination: Place, mode: TripMode, depart: string | null, restStops = false, vias: Place[] = []): Promise<TripResult> {
  const response = await fetch(`${BASE}/api/trip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      origin: placeBody(origin),
      destination: placeBody(destination),
      vias: vias.map(placeBody),
      mode,
      depart,
      rest_stops: restStops,
    }),
  })
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `Trip planning failed (${response.status})`)
  return (await response.json()) as TripResult
}

export interface SavedTrip {
  result: TripResult
  savedAt: number
}

export function saveLastTrip(result: TripResult) {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify({ result, savedAt: Date.now() }))
  } catch {
    return
  }
}

export function loadLastTrip(): SavedTrip | null {
  try {
    return JSON.parse(localStorage.getItem(LAST_KEY) ?? 'null') as SavedTrip | null
  } catch {
    return null
  }
}

export const REST_MODES: TripMode[] = ['car', 'bike']

export const directionsUrl = (lat: number, lon: number) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`

export const clock = (iso: string) => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })

export const dayClock = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })

export function duration(minutes: number) {
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return h ? `${h} h ${m.toString().padStart(2, '0')} min` : `${m} min`
}

export const HAZARD_LABELS: Record<string, string> = {
  thunder: 'Thunderstorm',
  rain: 'Rain',
  fog: 'Fog',
  wind: 'Strong wind',
  heat: 'Heat',
  cold: 'Cold',
  snow: 'Snow',
  convection: 'Storms en route',
  jet: 'Jet stream',
}

export function localInputValue(date: Date) {
  const shifted = new Date(date.getTime() + 5.5 * 3600 * 1000)
  return shifted.toISOString().slice(0, 16)
}
