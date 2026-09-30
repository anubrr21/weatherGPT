const BASE = import.meta.env.VITE_API_BASE ?? ''

export type FieldKey = 'temp' | 'wind' | 'rain' | 'cloud' | 'pressure'

export interface FieldData {
  generated: string
  lats: number[]
  lons: number[]
  step: number
  times: string[]
  hours_per_frame: number
  fields: Record<'temp' | 'u' | 'v' | 'speed' | 'rain' | 'cloud' | 'pressure', number[][]>
  source: string
}

export interface MapWarning {
  id: string
  event: string
  severity: string | null
  headline: string | null
  issuer: string | null
  areas: string[]
  expires: string | null
  rings: [number, number][][]
}

export interface WarningMap {
  fetched: string
  count: number
  mapped: number
  by_event: [string, number][]
  by_severity: [string, number][]
  warnings: MapWarning[]
}

export const mapApi = {
  fields: () =>
    fetch(`${BASE}/api/maps/fields`).then(async (r) => {
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `Map fields failed (${r.status})`)
      return r.json() as Promise<FieldData>
    }),
  warnings: () => fetch(`${BASE}/api/maps/warnings`).then((r) => r.json() as Promise<WarningMap>),
}

type Stop = [number, [number, number, number, number]]

export interface Scale {
  label: string
  unit: string
  stops: Stop[]
  ticks: number[]
}

export const SCALES: Record<FieldKey, Scale> = {
  temp: {
    label: 'Temperature',
    unit: '°C',
    ticks: [-10, 0, 10, 20, 30, 40],
    stops: [
      [-15, [120, 60, 200, 200]],
      [0, [60, 110, 230, 200]],
      [10, [40, 190, 220, 190]],
      [20, [70, 200, 110, 180]],
      [27, [245, 215, 70, 190]],
      [33, [250, 140, 50, 200]],
      [38, [235, 60, 60, 210]],
      [45, [170, 30, 110, 220]],
    ],
  },
  wind: {
    label: 'Wind speed',
    unit: 'km/h',
    ticks: [0, 20, 40, 60, 80],
    stops: [
      [0, [30, 60, 120, 120]],
      [10, [40, 120, 180, 150]],
      [20, [50, 180, 160, 170]],
      [35, [220, 210, 70, 190]],
      [50, [245, 140, 50, 210]],
      [70, [230, 60, 70, 220]],
      [90, [170, 40, 170, 230]],
    ],
  },
  rain: {
    label: 'Rain in 3 hours',
    unit: 'mm',
    ticks: [1, 5, 10, 20, 40],
    stops: [
      [0.2, [80, 160, 255, 0]],
      [0.5, [80, 160, 255, 110]],
      [2, [50, 120, 245, 170]],
      [7, [40, 80, 220, 200]],
      [15, [150, 70, 220, 215]],
      [30, [230, 60, 180, 230]],
      [50, [255, 90, 90, 240]],
    ],
  },
  cloud: {
    label: 'Cloud cover',
    unit: '%',
    ticks: [20, 50, 80, 100],
    stops: [
      [10, [230, 235, 245, 0]],
      [40, [220, 228, 240, 80]],
      [70, [230, 235, 245, 140]],
      [100, [250, 250, 255, 190]],
    ],
  },
  pressure: {
    label: 'Sea-level pressure',
    unit: 'hPa',
    ticks: [1000, 1005, 1010, 1015, 1020],
    stops: [
      [995, [150, 60, 200, 190]],
      [1003, [90, 120, 230, 170]],
      [1008, [120, 200, 220, 140]],
      [1012, [235, 235, 235, 110]],
      [1016, [250, 200, 110, 150]],
      [1022, [240, 130, 60, 180]],
      [1030, [200, 60, 60, 200]],
    ],
  },
}

export function colorAt(scale: Scale, value: number): [number, number, number, number] {
  const stops = scale.stops
  if (value <= stops[0][0]) return stops[0][1]
  for (let i = 1; i < stops.length; i++) {
    if (value <= stops[i][0]) {
      const [a, ca] = stops[i - 1]
      const [b, cb] = stops[i]
      const f = (value - a) / (b - a)
      return [ca[0] + (cb[0] - ca[0]) * f, ca[1] + (cb[1] - ca[1]) * f, ca[2] + (cb[2] - ca[2]) * f, ca[3] + (cb[3] - ca[3]) * f]
    }
  }
  return stops[stops.length - 1][1]
}

export function sampler(data: FieldData) {
  const { lats, lons, step } = data
  const rows = lats.length
  const cols = lons.length
  return (values: number[], lat: number, lon: number): number | null => {
    const y = (lat - lats[0]) / step
    const x = (lon - lons[0]) / step
    if (y < 0 || x < 0 || y > rows - 1 || x > cols - 1) return null
    const y0 = Math.floor(y)
    const x0 = Math.floor(x)
    const y1 = Math.min(rows - 1, y0 + 1)
    const x1 = Math.min(cols - 1, x0 + 1)
    const fy = y - y0
    const fx = x - x0
    const a = values[y0 * cols + x0]
    const b = values[y0 * cols + x1]
    const c = values[y1 * cols + x0]
    const d = values[y1 * cols + x1]
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy
  }
}

export const compass = (u: number, v: number) => {
  const from = (Math.atan2(-u, -v) * 180) / Math.PI
  const deg = (from + 360) % 360
  return ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(deg / 45) % 8]
}

export const frameLabel = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })
