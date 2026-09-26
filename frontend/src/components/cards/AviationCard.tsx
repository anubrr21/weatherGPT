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
          {data.wind_dir}° / {data.wind_kt} kt{data.gust_kt ? ` G${data.gust_kt}` : ''} · vis {data.visibility} · {data.temp_c}/{data.dewpoint_c}°C · Q{Math.round(data.altimeter_hpa ?? 0)}
        </span>
      </div>
      <pre className="raw">{data.raw_metar}</pre>
      {data.raw_taf && <pre className="raw taf">{data.raw_taf}</pre>}
    </CardShell>
  )
}
