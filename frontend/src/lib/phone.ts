import { clientId } from './live'
import type { Place } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface PhoneMessage {
  id: number
  direction: 'in' | 'out'
  channel: 'sms' | 'voice'
  kind: string
  text: string
  segments: number
  encoding: string
  status: string
  provider: string
  created_at: string
  data: Record<string, unknown>
}

export interface PhoneThread {
  phone: string
  provider: string
  subscriber: { place: string | null; district: string | null; language: string; confirmed: boolean; active: boolean; voice: boolean } | null
  messages: PhoneMessage[]
}

export interface IvrStep {
  call_id: string
  stage: string
  text: string
  audio_url: string
  gather: number | null
  timeout: number
  hangup: boolean
  language: string | null
}

export interface FamilyPhone {
  phone: string
  ref: string
  place: string | null
  language: string
  confirmed: boolean
}

export interface PhoneStatus {
  provider: string
  sms_number: string | null
  subscribers: number
  confirmed: number
  ivr_languages: string[]
  note: string | null
}

async function send<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${path} failed (${response.status})`)
  return data as T
}

export const phoneApi = {
  status: () => fetch(`${BASE}/api/phone/status`).then((r) => r.json() as Promise<PhoneStatus>),
  thread: (phone: string) => fetch(`${BASE}/api/phone/sim/thread?phone=${encodeURIComponent(phone)}`).then((r) => {
    if (!r.ok) throw new Error('Not a valid Indian mobile number')
    return r.json() as Promise<PhoneThread>
  }),
  sms: (phone: string, text: string) => send<{ replies: string[] }>('/api/phone/sim/sms', { phone, text }),
  call: (phone: string, callId: string | null, digits: string | null, extra: { reason?: string; message_id?: number } = {}) =>
    send<IvrStep>('/api/phone/sim/call', { phone, call_id: callId, digits, ...extra }),
  drill: (phone: string) => send<{ sms: boolean; call: number | null }>('/api/phone/sim/drill', { phone }),
  audioUrl: (path: string) => `${BASE}${path}`,
  family: () => fetch(`${BASE}/api/phone/family?client_id=${clientId()}`).then((r) => r.json() as Promise<{ phones: FamilyPhone[] }>),
  addFamily: (phone: string, place: Place, language: string) =>
    send<FamilyPhone & { provider: string }>('/api/phone/family', {
      client_id: clientId(), phone, name: place.name, lat: place.lat, lon: place.lon, district: place.district ?? null, state: place.state ?? null, language,
    }),
  removeFamily: (ref: string) => send<{ removed: boolean }>('/api/phone/family/remove', { client_id: clientId(), ref }),
}
