import { CloudOff, Gauge, RefreshCw, WifiOff } from 'lucide-react'
import type { Connection } from '../lib/connection'
import { savedAgo } from '../lib/offline'

interface Props {
  connection: Connection
  staleAt: number | null
  onRetry: () => void
  onLiteOff: () => void
}

export default function NetBanner({ connection, staleAt, onRetry, onLiteOff }: Props) {
  if (!connection.online) {
    return (
      <div className="net-banner offline" role="status">
        <WifiOff size={16} />
        <span>
          <b>You're offline</b>
          {staleAt ? `Showing the forecast saved ${savedAgo(staleAt)}. Warnings you already received are in the bell.` : 'Nothing saved for this place yet. Connect once to keep it for offline use.'}
        </span>
      </div>
    )
  }
  if (staleAt) {
    return (
      <div className="net-banner stale" role="status">
        <CloudOff size={16} />
        <span>
          <b>Can't reach WeatherGPT right now</b>
          Showing data saved {savedAgo(staleAt)}.
        </span>
        <button className="icon-btn" onClick={onRetry} aria-label="Try again">
          <RefreshCw size={15} />
        </button>
      </div>
    )
  }
  if (connection.lite) {
    return (
      <div className="net-banner lite" role="status">
        <Gauge size={16} />
        <span>
          <b>Data saver on</b>
          Because {connection.reason}: sky animation and radar paused, voice replies compressed.
        </span>
        <button className="net-action" onClick={onLiteOff}>
          Turn off
        </button>
      </div>
    )
  }
  return null
}
