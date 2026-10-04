import { API_ORIGIN, VERDICT_COLORS, span, when, type ShipmentCardData } from '../../lib/logistics'
import PdfButton from '../PdfButton'
import CardShell from './CardShell'

export default function ShipmentCard({ data }: { data: ShipmentCardData }) {
  return (
    <CardShell title={`${data.mode} · ${data.origin} → ${data.destination}`}>
      <div className="tripcard">
        <p>
          <b style={{ color: VERDICT_COLORS[data.verdict.code] }}>{data.verdict.label}</b> · {Math.round(data.distance_km).toLocaleString('en-IN')} km · arrive {when(data.arrive)}
        </p>
        <small>
          {data.cargo}
          {data.vehicle ? ` · ${data.vehicle}` : ''} · weather delay {data.delay_min ? span(data.delay_min) : 'none'}
          {data.delay_worst_min > data.delay_min ? ` (up to ${span(data.delay_worst_min)})` : ''} · {data.risk.toLowerCase()} risk · confidence {data.confidence.toLowerCase()}
        </small>
        {data.verdict.reasons.slice(0, 2).map((reason) => (
          <small key={reason}>{reason}</small>
        ))}
        <PdfButton url={`${API_ORIGIN}${data.report}`} name="WeatherGPT-shipment.pdf" label="Download the full PDF report" className="tripcard-open" />
      </div>
    </CardShell>
  )
}
