import { placeLabel, round } from '../../lib/format'
import type { AirData, Place } from '../../lib/types'
import CardShell from './CardShell'

const BANDS = [
  { max: 50, color: '#3fb56b' },
  { max: 100, color: '#9ccc4a' },
  { max: 200, color: '#f5c542' },
  { max: 300, color: '#f08a3a' },
  { max: 400, color: '#e5484d' },
  { max: 500, color: '#9b2c4f' },
]

export default function AirCard({ place, data }: { place: Place; data: AirData }) {
  const aqi = data.india_naqi ?? 0
  const color = BANDS.find((b) => aqi <= b.max)?.color ?? '#9b2c4f'
  const frac = Math.min(aqi / 500, 1)
  const r = 44
  const circumference = Math.PI * r
  const pollutants: [string, string, string][] = [
    ['PM2.5', 'pm2_5', 'µg/m³'],
    ['PM10', 'pm10', 'µg/m³'],
    ['NO₂', 'nitrogen_dioxide', 'µg/m³'],
    ['O₃', 'ozone', 'µg/m³'],
    ['SO₂', 'sulphur_dioxide', 'µg/m³'],
    ['CO', 'carbon_monoxide', 'µg/m³'],
  ]
  return (
    <CardShell place={place} title={`Air · ${placeLabel(place)}`} meta="India NAQI (CPCB method)">
      <div className="aqi">
        <svg viewBox="0 0 110 64" className="aqi-gauge" role="img" aria-label={`AQI ${aqi}`}>
          <path d="M 11 58 A 44 44 0 0 1 99 58" stroke="rgba(255,255,255,0.12)" strokeWidth={10} fill="none" strokeLinecap="round" />
          <path d="M 11 58 A 44 44 0 0 1 99 58" stroke={color} strokeWidth={10} fill="none" strokeLinecap="round" strokeDasharray={`${circumference * frac} ${circumference}`} />
          <text x={55} y={52} textAnchor="middle" className="aqi-num">{data.india_naqi ?? '—'}</text>
        </svg>
        <div>
          <b style={{ color }}>{data.india_naqi_band ?? 'Unknown'}</b>
          <span>Dominant: {data.dominant?.replace('pm2_5', 'PM2.5').replace('pm10', 'PM10') ?? '—'} · 24 h avg PM2.5 {round(data.pm2_5_24h_avg)} µg/m³</span>
        </div>
      </div>
      <div className="pollutants">
        {pollutants.map(([label, key, unit]) => (
          <div key={key}>
            <span>{label}</span>
            <b>{round(data.current[key])}</b>
            <small>{unit}</small>
          </div>
        ))}
      </div>
    </CardShell>
  )
}
