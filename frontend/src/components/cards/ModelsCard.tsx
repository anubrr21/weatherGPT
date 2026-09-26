import { dayMonth, placeLabel, round } from '../../lib/format'
import type { ModelCompare, Place } from '../../lib/types'
import CardShell from './CardShell'

const COLORS: Record<string, string> = {
  gfs_seamless: '#6fb7ff',
  ecmwf_ifs025: '#ffb35c',
  icon_seamless: '#9ae6b4',
}

type Cell = { tmax: number | null; tmin: number | null; rain: number | null; gust: number | null }

const W = 320
const H = 110

export default function ModelsCard({ place, data }: { place: Place; data: ModelCompare }) {
  const models = Object.keys(data.models)
  const cell = (day: ModelCompare['days'][number], m: string) => day[m] as Cell
  const values = data.days.flatMap((d) => models.map((m) => cell(d, m).tmax).filter((v): v is number => v !== null))
  const lo = Math.min(...values) - 1
  const hi = Math.max(...values) + 1
  const x = (i: number) => 20 + (i / Math.max(data.days.length - 1, 1)) * (W - 40)
  const y = (t: number) => 10 + (1 - (t - lo) / (hi - lo)) * (H - 36)
  const worst = data.days.reduce((a, d) => ((d.spread_tmax ?? 0) > (a.spread_tmax ?? 0) ? d : a), data.days[0])

  return (
    <CardShell place={place} title={`Model spread · ${placeLabel(place)}`} meta="Max temp, 7 days">
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Maximum temperature by model">
        {data.days.map((d, i) => {
          const spread = models.map((m) => cell(d, m).tmax).filter((v): v is number => v !== null)
          return spread.length ? (
            <rect key={d.date} x={x(i) - 7} y={y(Math.max(...spread))} width={14} height={Math.max(y(Math.min(...spread)) - y(Math.max(...spread)), 2)} rx={4} className="spread-band" />
          ) : null
        })}
        {models.map((m) => (
          <path
            key={m}
            d={data.days.map((d, i) => `${i ? 'L' : 'M'}${x(i)},${y(cell(d, m).tmax ?? lo)}`).join(' ')}
            stroke={COLORS[m]}
            strokeWidth={2}
            fill="none"
          />
        ))}
        {data.days.map((d, i) => (
          <text key={d.date} x={x(i)} y={H - 8} className="chart-axis" textAnchor="middle">{dayMonth(d.date).split(' ')[0]}</text>
        ))}
      </svg>
      <div className="legend">
        {models.map((m) => (
          <span key={m}><i style={{ background: COLORS[m] }} />{data.models[m]}</span>
        ))}
      </div>
      <div className="model-rain">
        {data.days.map((d) => (
          <div key={d.date}>
            <span>{dayMonth(d.date)}</span>
            {models.map((m) => (
              <b key={m} style={{ color: COLORS[m] }}>{round(cell(d, m).rain, 0)}</b>
            ))}
          </div>
        ))}
        <p>Rain (mm) per model. Widest max-temp disagreement: {round(worst?.spread_tmax, 1)}°C on {worst ? dayMonth(worst.date) : '—'}.</p>
      </div>
    </CardShell>
  )
}
