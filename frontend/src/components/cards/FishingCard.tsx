import { Anchor } from 'lucide-react'
import { placeLabel, round, weekday } from '../../lib/format'
import type { FishingData, Place, Verdict } from '../../lib/types'
import CardShell from './CardShell'

const TONE: Record<Verdict, string> = { GO: 'calm', CAUTION: 'moderate', 'NO-GO': 'extreme' }

export default function FishingCard({ place, data }: { place: Place; data: FishingData }) {
  return (
    <CardShell title={`Fishing · ${placeLabel(place)}`} meta="waves · gusts · IMD" tone={TONE[data.now]}>
      <div className={`verdict ${TONE[data.now]}`}>
        <Anchor size={22} />
        <b>{data.now}</b>
        <span>
          Waves {round(data.wave_now_m, 1)} m · gusts {round(data.gust_now_kmh)} km/h
        </span>
      </div>
      {data.official_sea_alerts.map((a) => (
        <p key={a.headline} className="card-note warn">IMD: {a.headline}</p>
      ))}
      {!data.available && <p className="card-note">No wave data for this point — verdict uses wind only. Pick a coastal village or harbour.</p>}
      <div className="verdict-days">
        {data.days.map((d, i) => (
          <div key={d.date} className={TONE[d.verdict]}>
            <span>{weekday(d.date, i)}</span>
            <b>{d.verdict}</b>
            <small>{round(d.wave_max_m, 1)} m · {round(d.gust_max_kmh)} km/h</small>
          </div>
        ))}
      </div>
      <p className="card-fine">{data.rules}</p>
    </CardShell>
  )
}
