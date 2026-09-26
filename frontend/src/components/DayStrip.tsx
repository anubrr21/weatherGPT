import { round, tempColor, weekday } from '../lib/format'
import type { Day } from '../lib/types'
import SkyGlyph from './SkyGlyph'

export default function DayStrip({ days }: { days: Day[] }) {
  const lo = Math.min(...days.map((d) => d.temperature_2m_min))
  const hi = Math.max(...days.map((d) => d.temperature_2m_max))
  const span = Math.max(hi - lo, 1)
  return (
    <section className="days" aria-label="10 day forecast">
      {days.map((d, i) => {
        const bottom = ((d.temperature_2m_min - lo) / span) * 100
        const height = Math.max(((d.temperature_2m_max - d.temperature_2m_min) / span) * 100, 6)
        return (
          <article key={d.time} className="day" title={`${d.condition.label}, rain ${round(d.precipitation_sum, 1)} mm`}>
            <span className="day-name">{weekday(d.time, i)}</span>
            <SkyGlyph sky={d.condition.sky} size={22} />
            <span className="day-hi">{round(d.temperature_2m_max)}°</span>
            <div className="day-bar">
              <span
                style={{
                  bottom: `${bottom}%`,
                  height: `${height}%`,
                  background: `linear-gradient(to top, ${tempColor(d.temperature_2m_min)}, ${tempColor(d.temperature_2m_max)})`,
                }}
              />
            </div>
            <span className="day-lo">{round(d.temperature_2m_min)}°</span>
            <span className={`day-rain ${(d.precipitation_probability_max ?? 0) >= 50 ? 'wet' : ''}`}>
              {d.precipitation_sum >= 0.5 ? `${round(d.precipitation_sum)}mm` : `${d.precipitation_probability_max ?? 0}%`}
            </span>
          </article>
        )
      })}
    </section>
  )
}
