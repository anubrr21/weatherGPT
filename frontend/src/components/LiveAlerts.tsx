import { Bell, BellRing, CheckCheck, MapPin, MessageSquareText, Radar, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { SEVERITY_TONE } from '../lib/format'
import type { LiveState } from '../lib/live'
import { isNative, notificationPermission, requestNotificationPermission, type Permission } from '../lib/native'
import { timeAgo, type Notice, type NoticeKind } from '../lib/notices'

type Tab = 'all' | 'warnings' | 'rain' | 'briefing'

const TABS: { id: Tab; label: string; kinds: NoticeKind[] | null }[] = [
  { id: 'all', label: 'All', kinds: null },
  { id: 'warnings', label: 'Warnings', kinds: ['official', 'heavy_rain', 'heat', 'wind', 'fog'] },
  { id: 'rain', label: 'Rain', kinds: ['rain_soon', 'storm'] },
  { id: 'briefing', label: 'Briefings', kinds: ['briefing'] },
]

const tone = (n: Notice) => (n.kind === 'briefing' ? 'info' : SEVERITY_TONE[n.severity] ?? (n.severity === 'Info' ? 'info' : 'minor'))

interface Props {
  state: LiveState
  notices: Notice[]
  unread: number
  open: boolean
  focus: number | null
  onOpenChange: (open: boolean) => void
  onSeen: (ids: number[]) => void
  onMarkAll: () => void
  onAsk: (notice: Notice) => void
  onRadar: (notice: Notice) => void
  onGo: (notice: Notice) => void
}

export function LiveBell({ state, notices, unread, open, focus, onOpenChange, onSeen, onMarkAll, onAsk, onRadar, onGo }: Props) {
  const [permission, setPermission] = useState<Permission>('unsupported')
  const [tab, setTab] = useState<Tab>('all')
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    notificationPermission().then(setPermission).catch(() => setPermission('unsupported'))
  }, [open])

  useEffect(() => {
    if (focus === null) return
    setTab('all')
    setExpanded(focus)
    onSeen([focus])
  }, [focus])

  const filter = TABS.find((t) => t.id === tab)?.kinds
  const shown = filter ? notices.filter((n) => filter.includes(n.kind)) : notices
  const counts = Object.fromEntries(TABS.map((t) => [t.id, t.kinds ? notices.filter((n) => !n.read && t.kinds!.includes(n.kind)).length : unread]))

  const toggle = (n: Notice) => {
    setExpanded((current) => (current === n.id ? null : n.id))
    if (!n.read) onSeen([n.id])
  }

  return (
    <div className="bell-wrap">
      <button
        className={`icon-btn glass bell ${state}`}
        onClick={() => onOpenChange(!open)}
        aria-label={`Notifications (${state})${unread ? `, ${unread} unread` : ''}`}
        title={state === 'live' ? 'Live alerts connected' : state === 'connecting' ? 'Connecting to live alerts…' : 'Live alerts offline, reconnecting'}
      >
        {unread ? <BellRing size={17} /> : <Bell size={17} />}
        <i className="bell-dot" />
        {unread > 0 && <b className="bell-count">{unread > 9 ? '9+' : unread}</b>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <header>
            <span>
              Notifications
              <small>{state === 'live' ? 'Live · official warnings and smart alerts for your places' : 'Reconnecting…'}</small>
            </span>
            {unread > 0 && (
              <button className="icon-btn" onClick={onMarkAll} aria-label="Mark all as read" title="Mark all as read">
                <CheckCheck size={16} />
              </button>
            )}
            <button className="icon-btn" onClick={() => onOpenChange(false)} aria-label="Close">
              <X size={16} />
            </button>
          </header>
          {permission !== 'granted' && permission !== 'unsupported' && (
            <button
              className="bell-enable"
              onClick={async () => setPermission(await requestNotificationPermission())}
              disabled={permission === 'denied'}
            >
              {permission === 'denied'
                ? isNative
                  ? 'Notifications are off for WeatherGPT in Android settings'
                  : 'Desktop notifications are blocked in browser settings'
                : isNative
                  ? 'Turn on warning notifications'
                  : 'Turn on desktop notifications'}
            </button>
          )}
          <nav className="bell-tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'on' : ''} onClick={() => setTab(t.id)}>
                {t.label}
                {counts[t.id] > 0 && <i>{counts[t.id]}</i>}
              </button>
            ))}
          </nav>
          {shown.length === 0 ? (
            <p className="bell-empty">
              {tab === 'briefing'
                ? 'Your morning briefing will appear here. Set its time in your profile.'
                : 'Nothing yet. Official warnings, rain starting soon, heat, wind and fog for your saved places will appear here.'}
            </p>
          ) : (
            <ul>
              {shown.map((n) => (
                <li key={n.id} className={`${tone(n)} ${n.read ? 'read' : 'unread'} ${expanded === n.id ? 'open' : ''}`}>
                  <button className="notice-head" onClick={() => toggle(n)} aria-expanded={expanded === n.id}>
                    <span className="bell-meta">
                      {!n.read && <i className="notice-dot" />}
                      {n.place.name} · {timeAgo(n.created_at)}
                      {n.kind === 'official' && <em className="notice-tag">IMD / NDMA</em>}
                    </span>
                    <b>{n.title}</b>
                    <small>{n.body}</small>
                  </button>
                  {expanded === n.id && (
                    <div className="notice-actions">
                      <button onClick={() => onAsk(n)}>
                        <MessageSquareText size={14} /> Ask WeatherGPT
                      </button>
                      {(n.kind === 'rain_soon' || n.kind === 'storm' || n.kind === 'heavy_rain') && (
                        <button onClick={() => onRadar(n)}>
                          <Radar size={14} /> Radar
                        </button>
                      )}
                      <button onClick={() => onGo(n)}>
                        <MapPin size={14} /> {n.place.name}
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export interface Toast {
  id: string
  severity: string
  title: string
  body: string
}

export function AlertToasts({ toasts, onDismiss, onOpen }: { toasts: Toast[]; onDismiss: (id: string) => void; onOpen: (id: string) => void }) {
  useEffect(() => {
    if (!toasts.length) return
    const id = setTimeout(() => onDismiss(toasts[0].id), 12000)
    return () => clearTimeout(id)
  }, [toasts])

  return (
    <div className="toasts" aria-live="assertive">
      {toasts.slice(0, 3).map((t) => (
        <article key={t.id} className={`toast ${SEVERITY_TONE[t.severity] ?? (t.severity === 'Info' ? 'info' : 'minor')}`}>
          <BellRing size={16} />
          <button className="toast-body" onClick={() => onOpen(t.id)}>
            <b>{t.title}</b>
            <small>{t.body}</small>
          </button>
          <button className="icon-btn" onClick={() => onDismiss(t.id)} aria-label="Dismiss">
            <X size={15} />
          </button>
        </article>
      ))}
    </div>
  )
}
