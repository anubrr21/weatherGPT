import type { Forecast } from './types'

const KEY = 'weathergpt:offline:v1'
const MAX_ENTRIES = 36

interface Entry {
  data: unknown
  savedAt: number
}

export interface Cached<T> {
  data: T
  savedAt: number
  cached: boolean
}

function read(): Record<string, Entry> {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, Entry>
  } catch {
    return {}
  }
}

function write(store: Record<string, Entry>) {
  const entries = Object.entries(store).sort((a, b) => b[1].savedAt - a[1].savedAt)
  for (let keep = Math.min(entries.length, MAX_ENTRIES); keep > 0; keep = Math.floor(keep * 0.7)) {
    try {
      localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(entries.slice(0, keep))))
      return
    } catch {
      continue
    }
  }
}

const keyFor = (kind: string, lat: number, lon: number) => `${kind}:${lat.toFixed(2)},${lon.toFixed(2)}`

export function remember(kind: string, lat: number, lon: number, data: unknown) {
  const store = read()
  store[keyFor(kind, lat, lon)] = { data, savedAt: Date.now() }
  write(store)
}

export function recall<T>(kind: string, lat: number, lon: number): Cached<T> | null {
  const entry = read()[keyFor(kind, lat, lon)]
  return entry ? { data: entry.data as T, savedAt: entry.savedAt, cached: true } : null
}

export async function withCache<T>(kind: string, lat: number, lon: number, fetcher: () => Promise<T>, online = true): Promise<Cached<T>> {
  if (!online) {
    const hit = recall<T>(kind, lat, lon)
    if (hit) return hit
  }
  try {
    const data = await fetcher()
    remember(kind, lat, lon, data)
    return { data, savedAt: Date.now(), cached: false }
  } catch (error) {
    const hit = recall<T>(kind, lat, lon)
    if (hit) return hit
    throw error
  }
}

export function savedAgo(savedAt: number) {
  const minutes = Math.round((Date.now() - savedAt) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} days ago`
}

export function offlineAnswer(fc: Forecast, place: string, savedAt: number) {
  const now = fc.current
  const today = fc.daily[0]
  const later = fc.hourly.filter((h) => (h.precipitation_probability ?? 0) >= 50).slice(0, 1)[0]
  const lines = [
    `You're offline, so I can't reach the live models. From the forecast saved ${savedAgo(savedAt)} for **${place}**:`,
    '',
    `- **Then:** ${Math.round(now.temperature_2m)}°C, feels like ${Math.round(now.apparent_temperature)}°C, humidity ${now.relative_humidity_2m}%, wind ${Math.round(now.wind_speed_10m)} km/h.`,
  ]
  if (today) {
    lines.push(
      `- **Today:** ${Math.round(today.temperature_2m_min)}–${Math.round(today.temperature_2m_max)}°C, rain ${today.precipitation_sum.toFixed(1)} mm` +
        (today.precipitation_probability_max !== null ? ` (chance ${today.precipitation_probability_max}%)` : '') +
        `, gusts up to ${Math.round(today.wind_gusts_10m_max)} km/h.`,
    )
  }
  if (later) lines.push(`- **Rain likely from** ${later.time.slice(11, 16)} (${later.precipitation_probability}% chance).`)
  const next = fc.daily.slice(1, 3)
  if (next.length) lines.push(`- **Next days:** ${next.map((d) => `${d.time.slice(5)} ${Math.round(d.temperature_2m_min)}–${Math.round(d.temperature_2m_max)}°C, rain ${d.precipitation_sum.toFixed(0)} mm`).join('; ')}.`)
  lines.push('', 'Warnings you already received are in the bell. I will answer properly as soon as you are back online.')
  return lines.join('\n')
}
