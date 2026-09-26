import { Droplets, Gauge, Navigation, Sun, Thermometer, Wind } from 'lucide-react'
import { round } from '../lib/format'
import type { Moment } from '../lib/sky'
import type { Forecast } from '../lib/types'

export default function Hud({ fc, m }: { fc: Forecast; m: Moment }) {
  const today = fc.daily[0]
  return (
    <section className="hud" aria-live="polite">
      <div className="hud-top">
        <span className={`live-pill ${m.live ? 'on' : ''}`}>{m.live ? 'LIVE' : `+${hoursAhead(fc.current.time, m.time)}H`}</span>
        <span className="hud-model">{fc.model_name} · {fc.timezone}</span>
      </div>
      <div className="hud-hero">
        <span className="hud-temp">{round(m.temperature)}<sup>°</sup></span>
        <div className="hud-cond">
          <strong>{m.label}</strong>
          <span>Feels {round(m.feelsLike)}° · H {round(today.temperature_2m_max)}° L {round(today.temperature_2m_min)}°</span>
        </div>
      </div>
      <dl className="readouts">
        <div>
          <dt><Wind size={13} /> Wind</dt>
          <dd>
            {round(m.windSpeed)}<small>km/h</small>
            <Navigation size={12} className="wind-arrow" style={{ transform: `rotate(${m.windDir + 180 - 45}deg)` }} />
          </dd>
        </div>
        <div>
          <dt><Gauge size={13} /> Gust</dt>
          <dd>{round(m.gust)}<small>km/h</small></dd>
        </div>
        <div>
          <dt><Droplets size={13} /> Rain</dt>
          <dd>{m.precipProb ?? 0}<small>%</small> <span className="dim">{round(m.precip, 1)}mm</span></dd>
        </div>
        <div>
          <dt><Thermometer size={13} /> RH</dt>
          <dd>{round(m.humidity)}<small>%</small></dd>
        </div>
        <div>
          <dt><Sun size={13} /> UV</dt>
          <dd>{round(m.uv, 1)}</dd>
        </div>
        <div>
          <dt>P<sub>msl</sub></dt>
          <dd>{round(fc.current.pressure_msl)}<small>hPa</small></dd>
        </div>
      </dl>
    </section>
  )
}

function hoursAhead(from: string, to: string) {
  return Math.max(1, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 3_600_000))
}
