import { useEffect, useRef, useState } from 'react'
import type { Notice } from './notices'
import type { OfficialAlert, Place } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const CLIENT_KEY = 'weathergpt:client-id'

export interface LiveAlert {
  receivedAt: number
  place: Place
  match: 'district' | 'state'
  alert: OfficialAlert
}

export type LiveState = 'connecting' | 'live' | 'offline'

export function clientId() {
  try {
    const existing = localStorage.getItem(CLIENT_KEY)
    if (existing) return existing
    const id = crypto.randomUUID().replace(/-/g, '')
    localStorage.setItem(CLIENT_KEY, id)
    return id
  } catch {
    return 'anon' + Math.random().toString(36).slice(2, 14)
  }
}

function socketUrl(id: string) {
  const base = BASE || window.location.origin
  const url = new URL('/ws', base)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('client_id', id)
  return url.toString()
}

export async function syncSubscriptions(places: Place[]) {
  const unique = places.filter((p, i) => places.findIndex((q) => Math.abs(q.lat - p.lat) < 0.01 && Math.abs(q.lon - p.lon) < 0.01) === i)
  await fetch(`${BASE}/api/subscriptions`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: clientId(),
      places: unique.slice(0, 20).map((p) => ({ name: p.name, lat: p.lat, lon: p.lon, district: p.district ?? null, state: p.state ?? null })),
    }),
  })
}

export function useLiveAlerts(onAlert: (alert: LiveAlert) => void, onNotice?: (notice: Notice) => void) {
  const [state, setState] = useState<LiveState>('connecting')
  const handler = useRef(onAlert)
  handler.current = onAlert
  const noticeHandler = useRef(onNotice)
  noticeHandler.current = onNotice

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry = 0
    let timer = 0
    let pinger = 0
    let closed = false

    const connect = () => {
      setState('connecting')
      socket = new WebSocket(socketUrl(clientId()))
      socket.onopen = () => {
        retry = 0
        setState('live')
        pinger = window.setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send('ping'), 25000)
      }
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string)
          if (data.type === 'alert') handler.current({ receivedAt: Date.now(), place: data.place, match: data.match, alert: data.alert })
          else if (data.type === 'notice') noticeHandler.current?.(data.notice as Notice)
        } catch {
          return
        }
      }
      socket.onclose = () => {
        clearInterval(pinger)
        if (closed) return
        setState('offline')
        retry += 1
        timer = window.setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(retry, 5)))
      }
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      clearInterval(pinger)
      socket?.close()
    }
  }, [])

  return state
}
