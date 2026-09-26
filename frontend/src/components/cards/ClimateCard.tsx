import { placeLabel, round } from '../../lib/format'
import type { ClimateData, Place } from '../../lib/types'
import CardShell from './CardShell'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function stripe(anomaly: number, range: number) {
  const k = Math.max(-1, Math.min(1, anomaly / range))
  if (k < 0) return `rgb(${Math.round(247 + k * 214)},${Math.round(247 + k * 145)},${Math.round(247 + k * 55)})`
  return `rgb(${Math.round(247 - k * 44)},${Math.round(247 - k * 223)},${Math.round(247 - k * 208)})`
}

export default function ClimateCard({ place, data }: { place: Place; data: ClimateData }) {
  const temps = data.annual.map((a) => a.mean_temp)
  const mean = temps.reduce((s, t) => s + t, 0) / Math.max(temps.length, 1)
  const range = Math.max(...temps.map((t) => Math.abs(t - mean)), 0.3)
  const last = data.month_by_year[data.month_by_year.length - 1]
  const normal = data.month_normal_1991_2020
  const trend = data.annual_temp_trend_c_per_decade ?? 0
  return (
    <CardShell place={place} title={`Climate · ${placeLabel(place)}`} meta={`${data.period} · ERA5`}>
      <div className="stripes" role="img" aria-label="Warming stripes, one bar per year">
        {data.annual.map((a) => (
          <span key={a.year} style={{ background: stripe(a.mean_temp - mean, range) }} title={`${a.year}: ${a.mean_temp.toFixed(2)} °C`} />
        ))}
      </div>
      <div className="stripes-axis">
        <span>{data.annual[0]?.year}</span>
        <span>{data.annual[data.annual.length - 1]?.year}</span>
      </div>
      <div className="stats">
        <div>
          <b className={trend > 0 ? 'warm' : 'cool'}>{trend > 0 ? '+' : ''}{round(trend, 2)}°C</b>
          <span>per decade</span>
        </div>
        <div>
          <b>{data.annual_rain_trend_mm_per_decade !== null && data.annual_rain_trend_mm_per_decade > 0 ? '+' : ''}{round(data.annual_rain_trend_mm_per_decade)}mm</b>
          <span>rain / decade</span>
        </div>
        <div>
          <b>{data.annual[data.annual.length - 1]?.hot_days_over_40 ?? 0}</b>
          <span>days ≥40° in {data.annual[data.annual.length - 1]?.year}</span>
        </div>
      </div>
      {last && (
        <p className="card-note">
          {MONTHS[data.month - 1]} {last.year}: {round(last.mean_temp, 1)}°C, {round(last.rain_total)} mm rain · 1991–2020 normal {round(normal.mean_temp, 1)}°C, {round(normal.rain_total)} mm
        </p>
      )}
    </CardShell>
  )
}
