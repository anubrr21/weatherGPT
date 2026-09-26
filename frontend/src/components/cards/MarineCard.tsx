import { dayMonth, placeLabel, round } from '../../lib/format'
import type { MarineData, Place } from '../../lib/types'
import CardShell from './CardShell'

function seaState(h: number) {
  if (h < 1.25) return { label: 'Slight — safe for small boats', tone: 'calm' }
  if (h < 2.5) return { label: 'Moderate — caution for small craft', tone: 'moderate' }
  if (h < 4) return { label: 'Rough — small boats should not venture', tone: 'severe' }
  return { label: 'Very rough / high — do not venture', tone: 'extreme' }
}

export default function MarineCard({ place, data }: { place: Place; data: MarineData }) {
  if (!data.available || !data.current) {
    return (
      <CardShell place={place} title={`Sea · ${placeLabel(place)}`}>
        <p className="card-note">{data.reason ?? 'No marine data.'}</p>
      </CardShell>
    )
  }
  const c = data.current
  const state = seaState(c.wave_height)
  const max = Math.max(...(data.daily ?? []).map((d) => d.wave_height_max), 1)
  return (
    <CardShell place={place} title={`Sea · ${placeLabel(place)}`} meta="Open-Meteo marine" tone={state.tone}>
      <div className="stats">
        <div><b>{round(c.wave_height, 1)}m</b><span>waves</span></div>
        <div><b>{round(c.wave_period, 1)}s</b><span>period</span></div>
        <div><b>{round(c.sea_surface_temperature, 1)}°</b><span>sea temp</span></div>
      </div>
      <p className={`sea-state ${state.tone}`}>{state.label}</p>
      <div className="wave-bars">
        {data.daily?.map((d) => (
          <div key={d.time}>
            <span style={{ height: `${(d.wave_height_max / max) * 100}%` }} className={seaState(d.wave_height_max).tone} />
            <b>{round(d.wave_height_max, 1)}</b>
            <small>{dayMonth(d.time)}</small>
          </div>
        ))}
      </div>
    </CardShell>
  )
}
