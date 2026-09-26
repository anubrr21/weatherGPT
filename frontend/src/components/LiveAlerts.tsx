import { Bell, BellRing, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { SEVERITY_TONE } from '../lib/format'
import type { LiveAlert, LiveState } from '../lib/live'
import { isNative, notificationPermission, requestNotificationPermission, type Permission } from '../lib/native'

const when = (ms: number) => new Date(ms).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
const until = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

interface Props {
  state: LiveState
  inbox: LiveAlert[]
  unread: number
  onOpen: () => void
  onAsk: (alert: LiveAlert) => void
}

export function LiveBell({ state, inbox, unread, onOpen, onAsk }: Props) {
  const [open, setOpen] = useState(false)
  const [permission, setPermission] = useState<Permission>('unsupported')

  useEffect(() => {
    notificationPermission().then(setPermission).catch(() => setPermission('unsupported'))
  }, [open])

  return (
    <div className="bell-wrap">
      <button
        className={`icon-btn glass bell ${state}`}
        onClick={() => {
          setOpen(!open)
          onOpen()
        }}
        aria-label={`Live alerts (${state})${unread ? `, ${unread} new` : ''}`}
        title={state === 'live' ? 'Live alerts connected' : state === 'connecting' ? 'Connecting to live alerts…' : 'Live alerts offline, reconnecting'}
      >
        {unread ? <BellRing size={17} /> : <Bell size={17} />}
        <i className="bell-dot" />
        {unread > 0 && <b className="bell-count">{unread > 9 ? '9+' : unread}</b>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Live alerts">
          <header>
            <span>
              Live IMD / NDMA alerts
              <small>{state === 'live' ? 'Connected · checked every 2 min' : 'Reconnecting…'}</small>
            </span>
            <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Close">
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
          {inbox.length === 0 ? (
            <p className="bell-empty">No warnings for your places right now. New IMD warnings will appear here the moment they are issued.</p>
          ) : (
            <ul>
              {inbox.map((a) => (
                <li key={a.alert.id} className={SEVERITY_TONE[a.alert.severity] ?? 'minor'}>
                  <button onClick={() => onAsk(a)}>
                    <span className="bell-meta">
                      {a.alert.severity} · {a.place.name}
                      {a.match === 'state' ? ' (state)' : ''} · {when(a.receivedAt)}
                    </span>
                    <b>{a.alert.event}</b>
                    <small>{a.alert.headline}</small>
                    <em>until {until(a.alert.expires)} · tap to ask what to do</em>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

export function AlertToasts({ toasts, onDismiss, onAsk }: { toasts: LiveAlert[]; onDismiss: (id: string) => void; onAsk: (a: LiveAlert) => void }) {
  useEffect(() => {
    if (!toasts.length) return
    const id = setTimeout(() => onDismiss(toasts[0].alert.id), 12000)
    return () => clearTimeout(id)
  }, [toasts])

  return (
    <div className="toasts" aria-live="assertive">
      {toasts.slice(0, 3).map((t) => (
        <article key={t.alert.id} className={`toast ${SEVERITY_TONE[t.alert.severity] ?? 'minor'}`}>
          <BellRing size={16} />
          <button className="toast-body" onClick={() => onAsk(t)}>
            <b>
              {t.alert.event ?? 'Weather alert'} · {t.place.name}
            </b>
            <small>{t.alert.headline}</small>
          </button>
          <button className="icon-btn" onClick={() => onDismiss(t.alert.id)} aria-label="Dismiss">
            <X size={15} />
          </button>
        </article>
      ))}
    </div>
  )
}
