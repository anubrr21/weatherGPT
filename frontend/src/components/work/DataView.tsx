import { Activity, Braces, Download, GitCompareArrows, Loader2, MessageSquareText, RadioTower, RefreshCw, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { apiDocsUrl, exportUrl, shortDay, workApi, type ResearchWorkspace } from '../../lib/work'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const MODEL_COLORS = ['#c4b3ff', '#6fb7ff', '#5fd39a', '#ffb35c']
const EXPORT_LABELS: Record<string, string> = {
  forecast: 'Hourly forecast, 48 h',
  models: 'Model comparison, 7 days',
  climate: 'Annual climate, 1991 onwards',
  observations: 'Station observations, 72 h',
}
const ENDPOINTS: [string, string][] = [
  ['/api/weather', 'Blended forecast: current, hourly and daily'],
  ['/api/alerts', 'Official CAP warnings matched to a place'],
  ['/api/maps/fields', 'Gridded wind, temperature, rain, cloud and pressure over India'],
  ['/api/maps/warnings', 'Every live warning with its polygon'],
  ['/api/cyclones/live', 'Active storms, tracks, cones and impact'],
  ['/api/cyclones/history', 'Storms near a place since 1980'],
  ['/api/lightning/live', 'Strikes, official areas and storm motion'],
  ['/api/verify', 'Model verification against station observations'],
  ['/api/trip', 'Route weather for a journey'],
]

function ClimateChart({ annual, trend }: { annual: NonNullable<ResearchWorkspace['climate']>['annual']; trend: number | null }) {
  const rows = annual.filter((a) => a.mean_temp !== null)
  if (rows.length < 5) return null
  const width = 640
  const height = 160
  const temps = rows.map((r) => r.mean_temp)
  const low = Math.min(...temps) - 0.2
  const high = Math.max(...temps) + 0.2
  const maxRain = Math.max(...rows.map((r) => r.rain_total))
  const x = (k: number) => (k / (rows.length - 1)) * width
  const y = (v: number) => height - ((v - low) / (high - low)) * (height - 10) - 5
  const line = rows.map((r, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(r.mean_temp).toFixed(1)}`).join(' ')
  const mean = temps.reduce((a, b) => a + b, 0) / temps.length
  const slope = trend !== null ? trend / 10 : 0
  const mid = (rows.length - 1) / 2
  return (
    <svg className="data-chart" viewBox={`0 0 ${width} ${height + 18}`} preserveAspectRatio="none" role="img" aria-label="Annual mean temperature and rainfall">
      {rows.map((r, k) => (
        <rect key={r.year} x={x(k) - 4} y={height - (r.rain_total / maxRain) * (height * 0.45)} width="8" height={(r.rain_total / maxRain) * (height * 0.45)} className="acc-rain" />
      ))}
      {trend !== null && <line x1={x(0)} x2={x(rows.length - 1)} y1={y(mean - slope * mid)} y2={y(mean + slope * mid)} className="data-trend" />}
      <path d={line} className="cy-chart-gust" />
      {rows.map((r, k) =>
        r.year % 5 === 0 ? (
          <text key={r.year} x={x(k)} y={height + 14} textAnchor="middle" className="cy-chart-day">
            {r.year}
          </text>
        ) : null,
      )}
      <text x="2" y={y(high) + 10} className="cy-chart-note">{high.toFixed(1)} °C</text>
      <text x="2" y={y(low) - 2} className="cy-chart-note">{low.toFixed(1)} °C</text>
    </svg>
  )
}

export default function DataView({ place, online, onAsk }: Props) {
  const [data, setData] = useState<ResearchWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache('research', place.lat, place.lon, () => workApi.research(place.lat, place.lon), online)
      setData(Array.isArray(result.data.stations) ? result.data : null)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, online])

  useEffect(() => {
    load()
  }, [load])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to open its data.</p></div>

  const models = data?.models
  const climate = data?.climate
  const modelKeys = models ? Object.keys(models.models) : []
  const maxRain = models ? Math.max(1, ...models.days.flatMap((d) => modelKeys.map((m) => d[m]?.rain ?? 0))) : 1

  return (
    <div className="cy data">
      <header className="trip-head cy-head">
        <h1>Data desk</h1>
        <p>Model disagreement, 35 years of climate, live station observations and downloads for {place.name}.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh data">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {loading && !data && <p className="trip-step">Loading model runs, reanalysis and observations…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing data saved {savedAgo(savedAt)}.</p>}

      {models && models.days.length > 0 && (
        <section className="trip-card">
          <h3>
            <GitCompareArrows size={15} /> Model comparison, next 7 days
          </h3>
          <div className="cy-stats">
            <span>
              <small>Mean Tmax spread</small>
              <b>{models.stats.mean_tmax_spread ?? '–'} °C</b>
            </span>
            <span>
              <small>Largest Tmax spread</small>
              <b>{models.stats.max_tmax_spread ?? '–'} °C</b>
              <em>{models.stats.max_tmax_spread_date ? shortDay(models.stats.max_tmax_spread_date) : ''}</em>
            </span>
            <span>
              <small>Largest rain spread</small>
              <b>{models.stats.max_rain_spread ?? '–'} mm</b>
              <em>{models.stats.max_rain_spread_date ? shortDay(models.stats.max_rain_spread_date) : ''}</em>
            </span>
            <span>
              <small>Wettest / driest model</small>
              <b>{models.stats.wettest_model ? models.models[models.stats.wettest_model] : '–'}</b>
              <em>driest {models.stats.driest_model ? models.models[models.stats.driest_model] : '–'}</em>
            </span>
          </div>
          <div className="acc-table-wrap">
            <table className="acc-table data-table">
              <thead>
                <tr>
                  <th>Day</th>
                  {modelKeys.map((m, k) => (
                    <th key={m} style={{ color: MODEL_COLORS[k % MODEL_COLORS.length] }}>
                      {models.models[m]}
                      <small>max / min °C · rain mm</small>
                    </th>
                  ))}
                  <th>
                    Spread<small>Tmax · rain</small>
                  </th>
                </tr>
              </thead>
              <tbody>
                {models.days.map((d) => (
                  <tr key={d.date}>
                    <td>{shortDay(d.date)} {d.date.slice(8)}</td>
                    {modelKeys.map((m, k) => {
                      const v = d[m]
                      return (
                        <td key={m}>
                          {v?.tmax ?? '–'} / {v?.tmin ?? '–'} · {v?.rain ?? '–'}
                          <i className="data-bar" style={{ width: `${((v?.rain ?? 0) / maxRain) * 100}%`, background: MODEL_COLORS[k % MODEL_COLORS.length] }} />
                        </td>
                      )
                    })}
                    <td className={d.spread_tmax >= 2 || d.spread_rain >= 10 ? 'top' : ''}>
                      {d.spread_tmax} · {d.spread_rain}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="trip-source">Spread is the largest difference between models. Large spread means low confidence in that day's forecast.</p>
        </section>
      )}

      {climate && climate.annual.length > 0 && (
        <section className="trip-card">
          <h3>
            <TrendingUp size={15} /> Climate record, {climate.period}
          </h3>
          <div className="cy-stats">
            <span>
              <small>Temperature trend</small>
              <b>
                {climate.annual_temp_trend_c_per_decade !== null ? `${climate.annual_temp_trend_c_per_decade > 0 ? '+' : ''}${climate.annual_temp_trend_c_per_decade.toFixed(2)} °C` : '–'}
              </b>
              <em>per decade</em>
            </span>
            <span>
              <small>Rainfall trend</small>
              <b>{climate.annual_rain_trend_mm_per_decade !== null ? `${climate.annual_rain_trend_mm_per_decade > 0 ? '+' : ''}${Math.round(climate.annual_rain_trend_mm_per_decade)} mm` : '–'}</b>
              <em>per decade</em>
            </span>
            <span>
              <small>
                {climate.stats.first_decade} → {climate.stats.last_decade}
              </small>
              <b>
                {climate.stats.temp_change_c !== undefined ? `${climate.stats.temp_change_c > 0 ? '+' : ''}${climate.stats.temp_change_c} °C` : '–'}
              </b>
              <em>{climate.stats.rain_change_mm !== undefined ? `${climate.stats.rain_change_mm > 0 ? '+' : ''}${climate.stats.rain_change_mm} mm rain` : ''}</em>
            </span>
            <span>
              <small>Days above 40 °C a year</small>
              <b>
                {climate.stats.hot_days_first ?? '–'} → {climate.stats.hot_days_last ?? '–'}
              </b>
            </span>
          </div>
          <ClimateChart annual={climate.annual} trend={climate.annual_temp_trend_c_per_decade} />
          <p>
            Warmest year {climate.stats.warmest_year ?? '–'}, wettest {climate.stats.wettest_year ?? '–'}, driest {climate.stats.driest_year ?? '–'}. Line: annual mean temperature with its linear trend; bars: annual rainfall.
          </p>
          <p className="trip-source">{climate.source}. The current year is incomplete.</p>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <RadioTower size={15} /> Station observations within 200 km
          </h3>
          {data.stations.length ? (
            <div className="acc-table-wrap">
              <table className="acc-table data-table">
                <thead>
                  <tr>
                    <th>Station</th>
                    <th>Type</th>
                    <th>Distance</th>
                    <th>Latest (UTC)</th>
                    <th>Temp / dew</th>
                    <th>Wind</th>
                    <th>Pressure</th>
                    <th>Reports, 72 h</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stations.map((s) => (
                    <tr key={s.station}>
                      <td>
                        <b>{s.name ?? s.station}</b>
                        <small>{s.station}</small>
                      </td>
                      <td>{s.kind}</td>
                      <td>{s.km} km</td>
                      <td>{s.latest.time.slice(5, 16).replace('T', ' ')}</td>
                      <td>
                        {s.latest.temp_c ?? '–'} / {s.latest.dewpoint_c ?? '–'} °C
                      </td>
                      <td>{s.latest.wind_kmh !== null ? `${Math.round(s.latest.wind_kmh)} km/h` : '–'}</td>
                      <td>{s.latest.pressure_hpa !== null ? `${s.latest.pressure_hpa} hPa` : '–'}</td>
                      <td>{s.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="rest-none">No station reports stored for this area in the last 72 hours.</p>
          )}
          <p className="trip-source">IMD synoptic stations arrive through the WMO WIS 2.0 network; airport reports are METARs. The archive only covers the hours the WeatherGPT server was running.</p>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <Download size={15} /> Downloads (CSV)
          </h3>
          <div className="data-downloads">
            {data.exports.map((kind) => (
              <a key={kind} href={exportUrl(kind, place.lat, place.lon)} download>
                <Download size={14} />
                <span>
                  <b>{EXPORT_LABELS[kind] ?? kind}</b>
                  <small>weathergpt_{kind}.csv</small>
                </span>
              </a>
            ))}
          </div>
        </section>
      )}

      <section className="trip-card">
        <h3>
          <Braces size={15} /> Open API
        </h3>
        <ul className="data-api">
          {ENDPOINTS.map(([path, text]) => (
            <li key={path}>
              <code>{path}</code>
              <span>{text}</span>
            </li>
          ))}
        </ul>
        <a className="cy-link" href={apiDocsUrl} target="_blank" rel="noreferrer">
          <Activity size={13} /> Interactive API documentation
        </a>
      </section>

      <button className="trip-ask" onClick={() => onAsk(`For ${place.name}: how much do GFS, ECMWF and ICON disagree this week and why, and what do the 1991 to present trends in temperature, rainfall and hot days show?`)}>
        <MessageSquareText size={16} /> Ask WeatherGPT to interpret the data
      </button>
      {data && <p className="trip-source">{data.source}.</p>}
    </div>
  )
}
