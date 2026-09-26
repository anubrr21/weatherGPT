import type { AviationData } from '../../lib/types'
import CardShell from './CardShell'

const CATEGORY_TONE: Record<string, string> = { VFR: 'calm', MVFR: 'minor', IFR: 'severe', LIFR: 'extreme' }

export default function AviationCard({ data }: { data: AviationData }) {
  if (!data.available) {
    return (
      <CardShell title={`METAR · ${data.station}`}>
        <p className="card-note">No recent report for this station.</p>
      </CardShell>
    )
  }
  return (
    <CardShell title={`${data.station} · ${data.name ?? ''}`} meta={data.observed ? new Date(data.observed).toUTCString().slice(17, 22) + 'Z' : undefined}>
      <div className="metar-top">
        <span className={`flight-cat ${CATEGORY_TONE[data.flight_category ?? ''] ?? 'minor'}`}>{data.flight_category ?? '—'}</span>
        <span>
          {data.wind_dir}° / {data.wind_kt} kt{data.gust_kt ? ` G${data.gust_kt}` : ''} · vis {data.decoded?.visibility ?? `${data.visibility} sm`} · {data.temp_c}/{data.dewpoint_c}°C · Q{Math.round(data.altimeter_hpa ?? 0)}
        </span>
      </div>
      {data.decoded && (
        <dl className="decoded">
          {data.decoded.hazards.length > 0 && (
            <div className="hazard">
              <dt>Hazards</dt>
              <dd>{data.decoded.hazards.join(', ')}</dd>
            </div>
          )}
          {data.decoded.wind && (
            <div>
              <dt>Wind</dt>
              <dd>{data.decoded.wind}</dd>
            </div>
          )}
          {data.decoded.visibility && (
            <div>
              <dt>Visibility</dt>
              <dd>{data.decoded.visibility}</dd>
            </div>
          )}
          {data.decoded.weather.length > 0 && (
            <div>
              <dt>Weather</dt>
              <dd>{data.decoded.weather.join(', ')}</dd>
            </div>
          )}
          <div>
            <dt>Cloud</dt>
            <dd>{data.decoded.clouds.join('; ') || 'no significant cloud'}</dd>
          </div>
          {data.decoded.trend && (
            <div>
              <dt>Trend</dt>
              <dd>{data.decoded.trend}</dd>
            </div>
          )}
        </dl>
      )}
      <pre className="raw">{data.raw_metar}</pre>
      {data.raw_taf && <pre className="raw taf">{data.raw_taf}</pre>}
    </CardShell>
  )
}
