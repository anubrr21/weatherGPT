import { Route } from 'lucide-react'
import { HAZARD_LABELS, dayClock, duration, levelColor, type TripResult } from '../../lib/trip'
import CardShell from './CardShell'

export default function TripCard({ data }: { data: TripResult }) {
  const route = data.routes[0]
  if (!route) return null
  return (
    <CardShell title={`${data.mode_label} · ${data.origin.name} → ${data.destination.name}`}>
      <div className="tripcard">
        <p>
          <b>{Math.round(route.distance_km)} km</b> · {duration(route.duration_min)} · arrive {dayClock(route.arrive)}
          <em style={{ color: levelColor(route.risk.score) }}> · {route.risk.label} risk</em>
        </p>
        <div className="trip-strip small">
          {route.points.slice(0, -1).map((p, k) => (
            <i key={p.i} style={{ flex: Math.max(0.5, route.points[k + 1].km - p.km), background: levelColor(Math.max(p.level, route.points[k + 1].level)) }} />
          ))}
        </div>
        {route.hazards.slice(0, 2).map((h, k) => (
          <small key={k}>
            {HAZARD_LABELS[h.kind] ?? h.kind}: {h.detail}
            {h.near ? ` near ${h.near}` : ''}
          </small>
        ))}
        {route.alerts.length > 0 && <small>{route.alerts.length} official warning{route.alerts.length > 1 ? 's' : ''} along the route</small>}
        <button className="tripcard-open" onClick={() => window.dispatchEvent(new CustomEvent('weathergpt:open-trip', { detail: data }))}>
          <Route size={14} /> Open in trip planner
        </button>
      </div>
    </CardShell>
  )
}
