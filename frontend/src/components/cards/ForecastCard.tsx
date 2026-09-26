import { hourLabel, placeLabel, round, tempColor, weekday } from '../../lib/format'
import type { Forecast, Place } from '../../lib/types'
import SkyGlyph from '../SkyGlyph'
import CardShell from './CardShell'

const W = 320
const H = 120
const PAD = 18

export default function ForecastCard({ place, data }: { place: Place; data: Forecast }) {
  const hours = data.hourly.slice(0, 48)
  const temps = hours.map((h) => h.temperature_2m)
  const lo = Math.min(...temps) - 1
  const hi = Math.max(...temps) + 1
  const x = (i: number) => PAD + (i / Math.max(hours.length - 1, 1)) * (W - PAD * 2)
  const y = (t: number) => 14 + (1 - (t - lo) / (hi - lo)) * (H - 50)
  const line = hours.map((h, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(h.temperature_2m).toFixed(1)}`).join(' ')
  const area = `${line} L${x(hours.length - 1)},${H - 30} L${x(0)},${H - 30} Z`
  const maxI = temps.indexOf(Math.max(...temps))
  const minI = temps.indexOf(Math.min(...temps))
  const gradId = `fg-${place.lat}-${place.lon}`.replace(/\./g, '')
  const c = data.current

  return (
    <CardShell title={placeLabel(place)} meta={`${data.model_name} · 48 h`}>
      <div className="fc-now">
        <SkyGlyph sky={c.condition.sky} size={30} />
        <span className="fc-temp">{round(c.temperature_2m)}°</span>
        <span className="fc-desc">
          {c.condition.label}
          <small>feels {round(c.apparent_temperature)}° · {c.relative_humidity_2m}% RH · {round(c.wind_speed_10m)} km/h {c.wind_compass}</small>
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="48 hour temperature and rain chart">
        <defs>
          <linearGradient id={gradId} x1="0" x2="1">
            {hours.filter((_, i) => i % 6 === 0).map((h, i, arr) => (
              <stop key={h.time} offset={`${(i / Math.max(arr.length - 1, 1)) * 100}%`} stopColor={tempColor(h.temperature_2m)} />
            ))}
          </linearGradient>
        </defs>
        {hours.map((h, i) => {
          const p = (h.precipitation_probability ?? 0) / 100
          return p > 0.03 ? (
            <rect key={h.time} x={x(i) - 2.2} y={H - 30 - p * 34} width={4.4} height={p * 34} rx={1.5} fill={`rgba(110,180,255,${0.25 + Math.min(h.precipitation / 4, 1) * 0.6})`} />
          ) : null
        })}
        <path d={area} fill={`url(#${gradId})`} opacity={0.14} />
        <path d={line} stroke={`url(#${gradId})`} strokeWidth={2.2} fill="none" strokeLinejoin="round" />
        {[maxI, minI].map((i) => (
          <g key={i}>
            <circle cx={x(i)} cy={y(temps[i])} r={3} fill={tempColor(temps[i])} />
            <text x={x(i)} y={y(temps[i]) - 7} className="chart-label" textAnchor="middle">{round(temps[i])}°</text>
          </g>
        ))}
        {hours.map((h, i) => (i % 6 === 0 ? <text key={h.time} x={x(i)} y={H - 14} className="chart-axis" textAnchor="middle">{hourLabel(h.time)}</text> : null))}
        <line x1={PAD} x2={W - PAD} y1={H - 30} y2={H - 30} className="chart-base" />
      </svg>
      <div className="fc-days">
        {data.daily.slice(0, 5).map((d, i) => {
          const conf = data.confidence?.find((c) => c.date === d.time)
          return (
            <div key={d.time}>
              <span>{weekday(d.time, i)}</span>
              <SkyGlyph sky={d.condition.sky} size={16} />
              <b>{round(d.temperature_2m_max)}°</b>
              <small>{round(d.temperature_2m_min)}°</small>
              <em>{round(d.precipitation_sum, d.precipitation_sum < 10 ? 1 : 0)}mm</em>
              {conf && (
                <i className={`conf conf-${conf.label.toLowerCase()}`} title={`${conf.label} confidence ${conf.score}/100 · ${conf.rain_agreement}`}>
                  {conf.label}
                </i>
              )}
            </div>
          )
        })}
      </div>
      {data.confidence?.length ? <p className="card-fine">Confidence = agreement between GFS, ECMWF and ICON, reduced with lead time.</p> : null}
    </CardShell>
  )
}
