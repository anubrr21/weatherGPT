import { hourLabel, placeLabel, round, tempColor } from '../../lib/format'
import type { Place, UrbanData } from '../../lib/types'
import CardShell from './CardShell'

const W = 320
const H = 90
const RISK_TONE = { low: 'calm', moderate: 'moderate', high: 'severe' } as const

export default function UrbanCard({ place, data }: { place: Place; data: UrbanData }) {
  const series = data.heat_series
  const values = series.map((s) => s.heat_index)
  const lo = Math.min(...values, 26) - 1
  const hi = Math.max(...values, 42) + 1
  const x = (i: number) => 14 + (i / Math.max(series.length - 1, 1)) * (W - 28)
  const y = (v: number) => 8 + (1 - (v - lo) / (hi - lo)) * (H - 28)
  const line = series.map((s, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(s.heat_index).toFixed(1)}`).join(' ')
  const peak = data.heat_index_peak

  return (
    <CardShell title={`City · ${placeLabel(place)}`} meta="heat index · rain intensity">
      <div className="fc-now">
        <span className="fc-temp" style={{ color: tempColor(peak.heat_index) }}>{round(peak.heat_index)}°</span>
        <span className="fc-desc">
          Feels-like peak at {peak.time.slice(11, 16)}
          <small>{peak.band}</small>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Heat index next 24 hours">
        {[32, 41].map((band) =>
          band > lo && band < hi ? (
            <g key={band}>
              <line x1={14} x2={W - 14} y1={y(band)} y2={y(band)} className="band-line" />
              <text x={W - 14} y={y(band) - 3} textAnchor="end" className="chart-axis">{band}°</text>
            </g>
          ) : null,
        )}
        <path d={line} fill="none" stroke={tempColor(peak.heat_index)} strokeWidth={2.2} />
        {series.map((s, i) => (i % 6 === 0 ? <text key={s.time} x={x(i)} y={H - 6} textAnchor="middle" className="chart-axis">{hourLabel(s.time)}</text> : null))}
      </svg>
      <div className="stats">
        <div>
          <b className={RISK_TONE[data.waterlogging_risk]}>{data.waterlogging_risk}</b>
          <span>waterlogging risk</span>
        </div>
        <div>
          <b>{round(data.max_hourly_rain_mm, 1)}</b>
          <span>max mm / hour</span>
        </div>
        <div>
          <b>{round(data.max_3h_rain_mm, 1)}</b>
          <span>max mm / 3 h</span>
        </div>
      </div>
      <div className="commutes">
        {data.commutes.map((c) => (
          <div key={c.slot}>
            <span>{c.slot.slice(5).replace(' ', ' · ')}</span>
            <b className={c.rain_prob >= 50 ? 'cool' : ''}>{c.rain_prob}% rain</b>
            <small>feels {round(c.heat_index)}°</small>
          </div>
        ))}
      </div>
    </CardShell>
  )
}
