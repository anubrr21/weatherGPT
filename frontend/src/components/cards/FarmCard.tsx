import { dayMonth, hourLabel, placeLabel, round } from '../../lib/format'
import type { FarmData, Place } from '../../lib/types'
import CardShell from './CardShell'

const BLOCKER: Record<string, string> = {
  rain: 'rain risk',
  wind: 'strong wind (drift)',
  calm: 'dead calm (inversion risk)',
  heat: 'heat / low humidity',
}

const THI_TONE: Record<string, string> = { none: 'calm', mild: 'minor', moderate: 'moderate', severe: 'severe' }

export default function FarmCard({ place, data }: { place: Place; data: FarmData }) {
  const hours = data.hourly.slice(0, 48)
  const inWindow = (t: string) => data.spray.windows.some((w) => t >= w.start && t < w.end)
  const irr = data.irrigation
  const need = Math.max(irr.crop_water_need_7d_mm, 1)
  const covered = Math.min(irr.effective_rain_7d_mm / need, 1)
  const w = data.spray.windows

  return (
    <CardShell place={place} title={`Farm · ${placeLabel(place)}`} meta={irr.crop ? `${irr.crop}${irr.stage ? ` · ${irr.stage}` : ''}` : 'agro-met'}>
      <h4 className="card-sub first">Spray windows · next 48 h</h4>
      <div className="spray-strip" role="img" aria-label="Hours suitable for spraying">
        {hours.map((h) => (
          <span key={h.time} className={inWindow(h.time) ? 'ok' : h.is_day ? 'no' : 'night'} title={`${h.time.slice(5, 16).replace('T', ' ')}`} />
        ))}
      </div>
      <div className="spray-axis">
        {hours.filter((_, i) => i % 12 === 0).map((h) => (
          <span key={h.time}>{hourLabel(h.time)}</span>
        ))}
      </div>
      <p className="card-note">
        {w.length
          ? w.slice(0, 3).map((x) => `${dayMonth(x.start.slice(0, 10))} ${x.start.slice(11, 16)}–${x.end.slice(11, 16)}`).join(' · ')
          : `No safe window — mostly blocked by ${BLOCKER[data.spray.main_blocker ?? ''] ?? 'weather'}.`}
      </p>

      <h4 className="card-sub">Water balance · 7 days</h4>
      <div className="balance">
        <div className="balance-bar">
          <span style={{ width: `${covered * 100}%` }} />
        </div>
        <div className="balance-legend">
          <span>Rain covers <b>{round(irr.effective_rain_7d_mm)}</b> of <b>{round(irr.crop_water_need_7d_mm)}</b> mm need</span>
          <b className={irr.deficit_mm > 20 ? 'warm' : 'cool'}>{irr.deficit_mm > 0 ? `−${round(irr.deficit_mm)}` : `+${round(-irr.deficit_mm)}`} mm</b>
        </div>
        <p className="card-note">{irr.advice}</p>
      </div>

      <div className="stats">
        <div>
          <b>{data.dry_spells[0]?.days ?? 0}d</b>
          <span>{data.dry_spells[0] ? `dry from ${dayMonth(data.dry_spells[0].from)}` : 'no dry spell'}</span>
        </div>
        <div>
          <b className={THI_TONE[data.livestock.level]}>{round(data.livestock.peak_thi)}</b>
          <span>livestock THI · {data.livestock.level}</span>
        </div>
        <div>
          <b>{round(irr.et0_7d_mm)}mm</b>
          <span>ET₀ this week</span>
        </div>
      </div>
      {data.heavy_rain_days.length > 0 && <p className="card-note warn">Heavy rain expected {data.heavy_rain_days.map(dayMonth).join(', ')} — clear field drains, delay fertiliser.</p>}
    </CardShell>
  )
}
