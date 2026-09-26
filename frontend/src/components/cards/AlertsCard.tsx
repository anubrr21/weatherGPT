import { useState } from 'react'
import { SEVERITY_TONE, placeLabel } from '../../lib/format'
import type { AlertsBundle, Place } from '../../lib/types'
import CardShell from './CardShell'

const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

export default function AlertsCard({ place, data }: { place: Place; data: AlertsBundle }) {
  const [open, setOpen] = useState<string | null>(null)
  const empty = !data.official.length && !data.derived.length
  return (
    <CardShell title={`Warnings · ${placeLabel(place)}`} meta="IMD / NDMA CAP + model" tone={empty ? 'calm' : undefined}>
      {empty && <p className="card-note">No active official warnings or model-flagged hazards for the next 5 days.</p>}
      {data.official.slice(0, 6).map((a) => (
        <article key={a.id} className={`alert-row ${SEVERITY_TONE[a.severity] ?? 'minor'}`}>
          <button className="alert-main" onClick={() => setOpen(open === a.id ? null : a.id)}>
            <span className="sev">{a.severity}</span>
            <span className="alert-text">
              <b>{a.event}</b> · {a.areas.slice(0, 3).join(', ')}
              {a.match === 'state' && <em> (state-level)</em>}
              <small>{a.headline}</small>
            </span>
          </button>
          {open === a.id && (
            <div className="alert-more">
              <p>Issued by {a.issuer ?? a.sender} · valid until {when(a.expires)}</p>
              {a.instruction && <p>→ {a.instruction}</p>}
              {a.localized.map((l) => (
                <p key={l.language} className="localized" lang={l.language?.toLowerCase() ?? undefined}>{l.headline}</p>
              ))}
            </div>
          )}
        </article>
      ))}
      {data.derived.length > 0 && <h4 className="card-sub">Model-derived (IMD thresholds, not official)</h4>}
      {data.derived.slice(0, 6).map((a, i) => (
        <article key={`${a.date}-${a.event}-${i}`} className={`alert-row derived ${SEVERITY_TONE[a.severity] ?? 'minor'}`}>
          <div className="alert-main">
            <span className="sev">{a.date.slice(5)}</span>
            <span className="alert-text">
              <b>{a.event}</b>
              <small>{a.detail}</small>
            </span>
          </div>
        </article>
      ))}
    </CardShell>
  )
}
