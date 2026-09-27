import { useCallback, useEffect, useRef, useState } from 'react'
import { clientId, type LiveState } from './live'
import type { CropEntry, Role } from './types'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const PREFS_KEY = 'weathergpt:notify-prefs'
const INBOX_KEY = 'weathergpt:inbox'

function savedInbox(): { unread: number; notices: Notice[] } {
  try {
    return JSON.parse(localStorage.getItem(INBOX_KEY) ?? 'null') ?? { unread: 0, notices: [] }
  } catch {
    return { unread: 0, notices: [] }
  }
}

export type NoticeKind = 'official' | 'rain_soon' | 'storm' | 'heavy_rain' | 'heat' | 'wind' | 'fog' | 'briefing'

export interface Notice {
  id: number
  kind: NoticeKind
  severity: string
  title: string
  body: string
  place: { name: string; lat: number; lon: number }
  data: Record<string, unknown>
  created_at: string
  read: boolean
  channel: string
}

export interface NotifyPrefs {
  briefing_at: string | null
  quiet_from: string | null
  quiet_to: string | null
  kinds: NoticeKind[]
}

export const NOTICE_KINDS: { kind: NoticeKind; label: string; hint: string; locked?: boolean }[] = [
  { kind: 'official', label: 'Official IMD warnings', hint: 'Always on', locked: true },
  { kind: 'rain_soon', label: 'Rain starting soon', hint: '15-minute nowcast' },
  { kind: 'storm', label: 'Thunderstorms', hint: 'Lightning ahead' },
  { kind: 'heavy_rain', label: 'Heavy rain', hint: 'IMD thresholds' },
  { kind: 'heat', label: 'Heat', hint: 'Feels-like peaks' },
  { kind: 'wind', label: 'Strong wind', hint: 'Gusts 50+ km/h' },
  { kind: 'fog', label: 'Dense fog', hint: 'The evening before' },
  { kind: 'briefing', label: 'Morning briefing', hint: 'Daily summary' },
]

export const DEFAULT_PREFS: NotifyPrefs = {
  briefing_at: '06:30',
  quiet_from: '22:00',
  quiet_to: '06:00',
  kinds: NOTICE_KINDS.map((k) => k.kind),
}

export function loadPrefs(): NotifyPrefs {
  try {
    const stored = JSON.parse(localStorage.getItem(PREFS_KEY) ?? 'null') as Partial<NotifyPrefs> | null
    return stored ? { ...DEFAULT_PREFS, ...stored } : DEFAULT_PREFS
  } catch {
    return DEFAULT_PREFS
  }
}

export function savePrefs(prefs: NotifyPrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
  } catch {
    return
  }
}

export async function syncPrefs(prefs: NotifyPrefs, language: string, role: Role, crops: CropEntry[]) {
  const kinds = Array.from(new Set<NoticeKind>(['official', ...prefs.kinds]))
  await fetch(`${BASE}/api/notifications/prefs`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId(), language, role, crops, briefing_at: prefs.briefing_at, quiet_from: prefs.quiet_from, quiet_to: prefs.quiet_to, kinds }),
  })
}

export async function sendTestNotice(kind: NoticeKind = 'briefing') {
  const response = await fetch(`${BASE}/api/notifications/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId(), kind }),
  })
  return (await response.json()) as { created: number; pushed: number; note: string | null }
}

export function useNotices(live: LiveState) {
  const [notices, setNotices] = useState<Notice[]>(() => savedInbox().notices)
  const [unread, setUnread] = useState(() => savedInbox().unread)
  const busy = useRef(false)

  const refresh = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    try {
      const response = await fetch(`${BASE}/api/notifications?client_id=${clientId()}&limit=60`)
      if (!response.ok) return
      const data = (await response.json()) as { unread: number; notices: Notice[] }
      setNotices(data.notices)
      setUnread(data.unread)
      try {
        localStorage.setItem(INBOX_KEY, JSON.stringify(data))
      } catch {
        return
      }
    } catch {
      return
    } finally {
      busy.current = false
    }
  }, [])

  const receive = useCallback((notice: Notice) => {
    setNotices((all) => (all.some((n) => n.id === notice.id) ? all : [notice, ...all].slice(0, 60)))
    if (!notice.read) setUnread((n) => n + 1)
  }, [])

  const markRead = useCallback(async (ids?: number[]) => {
    const targets = ids ?? []
    setNotices((all) => all.map((n) => (!ids || targets.includes(n.id) ? { ...n, read: true } : n)))
    setUnread((n) => (ids ? Math.max(0, n - targets.length) : 0))
    await fetch(`${BASE}/api/notifications/read`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId(), ids: targets, all: !ids }),
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    refresh()
    const onVisible = () => document.visibilityState === 'visible' && refresh()
    document.addEventListener('visibilitychange', onVisible)
    const timer = window.setInterval(refresh, 5 * 60 * 1000)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(timer)
    }
  }, [refresh])

  useEffect(() => {
    if (live === 'live') refresh()
  }, [live, refresh])

  return { notices, unread, refresh, receive, markRead }
}

export function timeAgo(iso: string) {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (minutes < 24 * 60) return `${Math.round(minutes / 60)} h ago`
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
