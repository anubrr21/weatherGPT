import { Award, Gauge, Loader2, MessageSquareText, Plane, RefreshCw, Target } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import { MODEL_COLORS, fetchScorecard, type BoardRow, type Scorecard, type VerifyStation } from '../../lib/verify'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const WINDOWS = [7, 10, 14, 30]
const COLUMNS: { key: keyof BoardRow; label: string; unit: string; better: 'low' | 'high' }[] = [
  { key: 'temp_mae', label: 'Temperature', unit: '°C', better: 'low' },
  { key: 'dew_mae', label: 'Humidity (dew point)', unit: '°C', better: 'low' },
  { key: 'wind_mae', label: 'Wind', unit: 'km/h', better: 'low' },
  { key: 'rain_hss', label: 'Rain skill', unit: '', better: 'high' },
]

function biasText(bias: number | undefined | null, unit: string, warm: string, cold: string) {
  if (bias === undefined || bias === null) return null
  if (Math.abs(bias) < 0.2) return `no clear bias`
  return `${Math.abs(bias).toFixed(1)} ${unit} too ${bias > 0 ? warm : cold} on average`
}

function Chart({ station }: { station: VerifyStation }) {
  const { time, observed, rain, models } = station.series
  if (time.length < 6) return null
  const width = 640
  const height = 170
  const values = [...observed, ...Object.values(models).flat()].filter((v): v is number => v !== null)
  const low = Math.floor(Math.min(...values) - 1)
  const high = Math.ceil(Math.max(...values) + 1)
  const x = (k: number) => (k / (time.length - 1)) * width
  const y = (v: number) => height - ((v - low) / (high - low)) * (height - 10) - 5
  const path = (series: (number | null)[]) => {
    let d = ''
    series.forEach((v, k) => {
      if (v === null) return
      d += `${d && series[k - 1] !== null ? 'L' : 'M'}${x(k).toFixed(1)},${y(v).toFixed(1)} `
    })
    return d
  }
  return (
    <figure className="acc-chart">
      <svg viewBox={`0 0 ${width} ${height + 18}`} preserveAspectRatio="none" role="img" aria-label={`Observed and forecast temperature at ${station.name}`}>
        {rain.map((r, k) => (r ? <rect key={`r${k}`} x={x(k) - 2} y={0} width="4" height={height} className="acc-rain" /> : null))}
        {[low, Math.round((low + high) / 2), high].map((v) => (
          <g key={v}>
            <line x1="0" x2={width} y1={y(v)} y2={y(v)} className="cy-chart-rule" />
            <text x="2" y={y(v) - 3} className="cy-chart-note">
              {v}°
            </text>
          </g>
        ))}
        {Object.entries(models).map(([m, series]) => (
          <path key={m} d={path(series)} fill="none" stroke={MODEL_COLORS[m] ?? '#fff'} strokeWidth={m === 'best_match' ? 2.4 : 1.4} opacity={m === 'best_match' ? 1 : 0.75} vectorEffect="non-scaling-stroke" />
        ))}
        <path d={path(observed)} fill="none" stroke="#ffffff" strokeWidth={2.6} strokeDasharray="1 5" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {time.map((t, k) =>
          t.includes('T18:00') ? (
            <text key={t} x={x(k)} y={height + 14} textAnchor="middle" className="cy-chart-day">
              {new Date(t).toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'Asia/Kolkata' })}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption>
        <span>
          <i className="obs" /> Observed ({station.icao})
        </span>
        <span>
          <i style={{ background: MODEL_COLORS.best_match }} /> WeatherGPT blend
        </span>
        <span>
          <i style={{ background: MODEL_COLORS.ecmwf_ifs025 }} /> ECMWF
        </span>
        <span>
          <i style={{ background: MODEL_COLORS.gfs_seamless }} /> GFS
        </span>
        <span>
          <i style={{ background: MODEL_COLORS.icon_seamless }} /> ICON
        </span>
        <span>
          <i className="rain" /> rain observed
        </span>
      </figcaption>
    </figure>
  )
}

export default function AccuracyView({ place, online, onAsk }: Props) {
  const [days, setDays] = useState(10)
  const [card, setCard] = useState<Scorecard | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [station, setStation] = useState(0)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache(`verify-${days}`, place.lat, place.lon, () => fetchScorecard(place.lat, place.lon, days), online)
      setCard(Array.isArray(result.data.leaderboard) && Array.isArray(result.data.stations) ? result.data : null)
      setSavedAt(result.cached ? result.savedAt : null)
      setStation(0)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, days, online])

  useEffect(() => {
    load()
  }, [load])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to see forecast accuracy.</p></div>

  const blend = card?.leaderboard.find((r) => r.model === 'best_match')
  const nearest = card?.stations[station]
  const blendScores = nearest?.scores.best_match
  const best = card?.best
  const columnBest = (key: keyof BoardRow, better: 'low' | 'high') => {
    const values = (card?.leaderboard ?? []).map((r) => r[key]).filter((v): v is number => typeof v === 'number')
    return values.length ? (better === 'low' ? Math.min(...values) : Math.max(...values)) : null
  }

  return (
    <div className="cy acc">
      <header className="trip-head cy-head">
        <h1>Forecast accuracy</h1>
        <p>How close each weather model's day-ahead forecast came to what IMD's airport stations actually measured near {place.name}.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh accuracy">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      <div className="chips">
        {WINDOWS.map((d) => (
          <button key={d} className={days === d ? 'on' : ''} onClick={() => setDays(d)}>
            last {d} days
          </button>
        ))}
      </div>

      {loading && !card && <p className="trip-step">Comparing nine models with station observations…</p>}
      {error && !card && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing the scorecard saved {savedAgo(savedAt)}.</p>}
      {card && card.stations.length === 0 && <p className="trip-error">No IMD airport station with enough observations within 250 km of {place.name}.</p>}

      {card && best && blend && (
        <section className="acc-hero">
          <Award size={24} />
          <div>
            <b>
              Around {place.name}, {best.label} has been the most accurate over the last {card.days} days.
            </b>
            <p>
              WeatherGPT's own blend ranks {blend.rank} of {card.leaderboard.length}
              {blend.temp_mae !== null ? `, missing the temperature by ${blend.temp_mae.toFixed(1)} °C on average` : ''}
              {blendScores?.temp['1'] ? ` (${biasText(blendScores.temp['1'].bias, '°C', 'warm', 'cool')} at ${nearest?.icao})` : ''}.
              {blendScores?.rain['1']?.pod !== null && blendScores?.rain['1']?.pod !== undefined
                ? ` It caught ${Math.round((blendScores.rain['1'].pod ?? 0) * 100)}% of the rainy hours${blendScores.rain['1'].far !== null ? `, and ${Math.round((blendScores.rain['1'].far ?? 0) * 100)}% of the rain it forecast did not come` : ''}.`
                : ''}
            </p>
          </div>
        </section>
      )}

      {card && card.leaderboard.length > 0 && (
        <section className="trip-card">
          <h3>
            <Target size={15} /> Day-ahead scorecard, {card.stations.length} station{card.stations.length === 1 ? '' : 's'}
          </h3>
          <div className="acc-table-wrap">
            <table className="acc-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Model</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key}>
                      {c.label}
                      <small>{c.better === 'low' ? `avg error ${c.unit}` : 'HSS, higher is better'}</small>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.leaderboard.map((row) => (
                  <tr key={row.model} className={row.model === 'best_match' ? 'ours' : ''}>
                    <td>{row.rank}</td>
                    <td>{row.label}</td>
                    {COLUMNS.map((c) => {
                      const value = row[c.key] as number | null
                      const top = columnBest(c.key, c.better)
                      return (
                        <td key={c.key} className={value !== null && value === top ? 'top' : ''}>
                          {value === null ? '–' : c.unit ? value.toFixed(1) : value.toFixed(2)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="trip-source">Ranked by average error relative to the middle model across temperature, humidity and wind. Green marks the best in each column.</p>
        </section>
      )}

      {card && nearest && (
        <section className="trip-card">
          <h3>
            <Plane size={15} /> Observed vs forecast temperature, last 7 days
          </h3>
          {card.stations.length > 1 && (
            <div className="chips">
              {card.stations.map((s, k) => (
                <button key={s.icao} className={k === station ? 'on' : ''} onClick={() => setStation(k)}>
                  {s.city ?? s.name} ({s.icao}) · {Math.round(s.km)} km
                </button>
              ))}
            </div>
          )}
          <Chart station={nearest} />
          <div className="cy-stats">
            {(['best_match', 'ecmwf_ifs025', 'gfs_seamless', 'icon_seamless'] as const).map((m) => {
              const d1 = nearest.scores[m]?.temp['1']
              const d2 = nearest.scores[m]?.temp['2']
              return (
                <span key={m}>
                  <small>{card.models.find((x) => x.model === m)?.label}</small>
                  <b>
                    {d1 ? `${d1.mae.toFixed(1)} °C` : '–'}
                    <em> → {d2 ? `${d2.mae.toFixed(1)} °C` : '–'}</em>
                  </b>
                  <em>1 day ahead → 2 days ahead</em>
                </span>
              )
            })}
          </div>
          <p className="trip-source">
            {nearest.name}: {nearest.observations} hourly observations in {card.days} days. Dotted white line is what was measured; shaded columns are hours when rain or thunderstorms were reported.
          </p>
        </section>
      )}

      {card && (
        <section className="trip-card">
          <h3>
            <Gauge size={15} /> How this is measured
          </h3>
          <p>{card.method}</p>
          <p className="trip-source">Updated {new Date(card.generated).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' })}. Forecasts: Open-Meteo previous-runs archive. Observations: METAR via the Iowa Environmental Mesonet.</p>
        </section>
      )}

      <button className="trip-ask" onClick={() => onAsk(`Which weather model has been most accurate for ${place.name} lately, and how much should I trust the forecast for the next two days?`)}>
        <MessageSquareText size={16} /> Ask WeatherGPT about forecast reliability here
      </button>
    </div>
  )
}
