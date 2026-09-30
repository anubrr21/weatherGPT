import { AlertTriangle, Cloud, CloudRain, Gauge, Loader2, Pause, Play, RefreshCw, Thermometer, Wind } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { severityColor } from '../../lib/lightning'
import { frameLabel, mapApi, type FieldData, type FieldKey, type WarningMap } from '../../lib/maps'
import type { Place } from '../../lib/types'
import FieldMap from './FieldMap'

interface Props {
  place: Place | null
  online: boolean
  lite: boolean
}

const FIELDS: { key: FieldKey; label: string; icon: typeof Wind }[] = [
  { key: 'wind', label: 'Wind', icon: Wind },
  { key: 'temp', label: 'Temperature', icon: Thermometer },
  { key: 'rain', label: 'Rain', icon: CloudRain },
  { key: 'cloud', label: 'Clouds', icon: Cloud },
  { key: 'pressure', label: 'Pressure', icon: Gauge },
]

const SEVERITY_ORDER = ['Extreme', 'Severe', 'Moderate', 'Minor', 'Unknown']

export default function MapsView({ place, online, lite }: Props) {
  const [data, setData] = useState<FieldData | null>(null)
  const [warnings, setWarnings] = useState<WarningMap | null>(null)
  const [field, setField] = useState<FieldKey>('wind')
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [showWarnings, setShowWarnings] = useState(true)
  const [particles, setParticles] = useState(!lite)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!online) return
    setLoading(true)
    setError(null)
    try {
      const [fields, alerts] = await Promise.all([mapApi.fields(), mapApi.warnings().catch(() => null)])
      setData(Array.isArray(fields.times) && fields.fields ? fields : null)
      setWarnings(alerts && Array.isArray(alerts.warnings) ? alerts : null)
      const now = Date.now()
      const nearest = fields.times.reduce((best, t, k) => (Math.abs(new Date(t).getTime() - now) < Math.abs(new Date(fields.times[best]).getTime() - now) ? k : best), 0)
      setFrame(nearest)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [online])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!playing || !data) return
    const id = window.setInterval(() => setFrame((f) => (f + 1) % data.times.length), 900)
    return () => window.clearInterval(id)
  }, [playing, data])

  const grouped = useMemo(() => {
    if (!warnings) return []
    return [...warnings.warnings].sort((a, b) => SEVERITY_ORDER.indexOf(a.severity ?? 'Unknown') - SEVERITY_ORDER.indexOf(b.severity ?? 'Unknown') || a.event.localeCompare(b.event))
  }, [warnings])

  const hoursAhead = data ? Math.round((new Date(data.times[frame]).getTime() - Date.now()) / 3600000) : 0

  return (
    <div className="cy maps">
      <header className="trip-head cy-head">
        <h1>Weather map</h1>
        <p>India's wind, temperature, rain, cloud and pressure for the next 48 hours, with every live official warning drawn where it applies.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh map">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {!online && <p className="trip-error">The weather map needs a connection.</p>}
      {error && <p className="trip-error">{error}</p>}

      <div className="chips map-fields" role="radiogroup" aria-label="Map layer">
        {FIELDS.map(({ key, label, icon: Icon }) => (
          <button key={key} role="radio" aria-checked={field === key} className={field === key ? 'on' : ''} onClick={() => setField(key)}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      <FieldMap data={data} field={field} frame={frame} particles={particles && field === 'wind'} warnings={warnings?.warnings ?? []} showWarnings={showWarnings} place={place} />

      {data && (
        <div className="map-time">
          <button className="icon-btn glass" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause' : 'Play forecast'}>
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </button>
          <input type="range" min={0} max={data.times.length - 1} value={frame} onChange={(e) => setFrame(Number(e.target.value))} aria-label="Forecast time" />
          <span>
            <b>{frameLabel(data.times[frame])}</b>
            <small>{hoursAhead === 0 ? 'now' : hoursAhead > 0 ? `in ${hoursAhead} h` : `${-hoursAhead} h ago`}</small>
          </span>
        </div>
      )}

      <div className="chips">
        <label className="switch">
          <input type="checkbox" checked={showWarnings} onChange={(e) => setShowWarnings(e.target.checked)} />
          <span>Official warnings</span>
        </label>
        {field === 'wind' && (
          <label className="switch">
            <input type="checkbox" checked={particles} onChange={(e) => setParticles(e.target.checked)} />
            <span>Moving wind</span>
          </label>
        )}
      </div>
      {data && <p className="trip-source">{data.source}. Hover or tap the map for values. Generated {new Date(data.generated).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })}.</p>}

      {warnings && (
        <section className="trip-card">
          <h3>
            <AlertTriangle size={15} /> {warnings.count} official warning{warnings.count === 1 ? '' : 's'} in force across India
          </h3>
          <div className="map-counts">
            {warnings.by_event.map(([event, count]) => (
              <span key={event}>
                <b>{count}</b> {event}
              </span>
            ))}
          </div>
          <ul className="lt-warnings">
            {grouped.map((w) => (
              <li key={w.id}>
                <div className="map-warning">
                  <i style={{ background: severityColor(w.severity) }} />
                  <span>
                    <b>
                      {w.event} · {w.areas.join(', ').slice(0, 120)}
                    </b>
                    <small>
                      {w.severity} · {(w.issuer ?? '').replace(/^.*\(/, '').replace(/\)$/, '')}
                      {w.expires ? ` · until ${frameLabel(w.expires)}` : ''}
                    </small>
                  </span>
                </div>
              </li>
            ))}
          </ul>
          <p className="trip-source">NDMA SACHET common alerting feed: IMD, Central Water Commission and state disaster management authorities, each drawn with its own warning polygon.</p>
        </section>
      )}
    </div>
  )
}
