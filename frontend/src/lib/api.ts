import type { AlertsBundle, ChatEvent, Forecast, Insight, Place, Profile } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function get<T>(path: string, params: Record<string, string | number>): Promise<T> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
  const response = await fetch(`${BASE}${path}?${query}`)
  if (!response.ok) throw new Error(`${path} failed (${response.status})`)
  return response.json() as Promise<T>
}

export interface Health {
  ok: boolean
  llm: boolean
  neural_voice?: boolean
  server_stt?: boolean
  providers: { name: string; model: string }[]
}

export const api = {
  health: () => fetch(`${BASE}/api/health`).then((r) => r.json() as Promise<Health>),
  forecast: (lat: number, lon: number) => get<Forecast>('/api/weather', { lat, lon }),
  reverse: (lat: number, lon: number) => get<Place>('/api/reverse', { lat, lon }),
  geocode: (q: string) => get<Place[]>('/api/geocode', { q }),
  alerts: (lat: number, lon: number) => get<AlertsBundle>('/api/alerts', { lat, lon }),
  insights: (lat: number, lon: number, profile: Profile) =>
    get<Insight[]>('/api/insights', {
      lat,
      lon,
      role: profile.role,
      ...(profile.crops[0] ? { crop: profile.crops[0].name, stage: profile.crops[0].stage ?? '' } : {}),
    }),
}

export interface ChatPayload {
  message: string
  history: { role: string; text: string }[]
  lat?: number
  lon?: number
  place_name?: string
  place_label?: string
  language: string
  profile: Profile
}

export async function streamChat(payload: ChatPayload, onEvent: (e: ChatEvent) => void, signal?: AbortSignal) {
  const response = await fetch(`${BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok || !response.body) throw new Error(`Chat failed (${response.status})`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = frame
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trim())
        .join('')
      if (data) onEvent(JSON.parse(data) as ChatEvent)
      boundary = buffer.indexOf('\n\n')
    }
  }
}
