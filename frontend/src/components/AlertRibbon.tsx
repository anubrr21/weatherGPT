import { ShieldAlert, TriangleAlert } from 'lucide-react'
import { SEVERITY_TONE } from '../lib/format'
import type { AlertsBundle } from '../lib/types'

export default function AlertRibbon({ bundle, onAsk }: { bundle: AlertsBundle | null; onAsk: (q: string) => void }) {
  if (!bundle) return null
  const official = bundle.official[0]
  const derived = bundle.derived[0]
  if (!official && !derived) {
    return (
      <div className="ribbon calm">
        <ShieldAlert size={15} />
        <span>No IMD warnings or model-flagged hazards nearby</span>
      </div>
    )
  }
  const tone = SEVERITY_TONE[official?.severity ?? derived?.severity ?? 'Minor']
  const count = bundle.official.length + bundle.derived.length
  return (
    <button className={`ribbon ${tone}`} onClick={() => onAsk('What weather warnings are active for my area, and what should I do?')}>
      <TriangleAlert size={15} />
      <span className="ribbon-text">
        {official ? (
          <>
            <b>IMD · {official.event ?? official.severity}</b> {official.headline}
          </>
        ) : (
          <>
            <b>{derived.event}</b> {derived.date} — {derived.detail}
          </>
        )}
      </span>
      {count > 1 && <span className="ribbon-count">+{count - 1}</span>}
    </button>
  )
}
