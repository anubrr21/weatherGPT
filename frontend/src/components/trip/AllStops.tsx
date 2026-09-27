import { Coffee, MapPinned, Navigation, Phone } from 'lucide-react'
import { useMemo, useState } from 'react'
import { clock, directionsUrl, duration, type AlongPlace, type StopsAlong } from '../../lib/trip'
import { GoogleRating, KIND } from './stopKinds'

type Filter = 'all' | 'plaza' | 'fuel' | 'food' | 'stay'

const FILTERS: { id: Filter; label: string; kinds: AlongPlace['kind'][] | null }[] = [
  { id: 'all', label: 'All', kinds: null },
  { id: 'plaza', label: 'Plazas', kinds: ['services', 'rest_area'] },
  { id: 'fuel', label: 'Fuel', kinds: ['fuel'] },
  { id: 'food', label: 'Food', kinds: ['restaurant', 'fast_food', 'cafe'] },
  { id: 'stay', label: 'Stays', kinds: ['hotel', 'motel', 'guest_house'] },
]


export default function AllStops({ along, mode }: { along: StopsAlong; mode: string }) {
  const [filter, setFilter] = useState<Filter>('all')
  const kinds = FILTERS.find((f) => f.id === filter)?.kinds
  const shown = useMemo(() => (kinds ? along.places.filter((p) => kinds.includes(p.kind)) : along.places), [along, filter])
  const rated = along.places.some((p) => p.google)

  if (along.error && !along.places.length) return <p className="rest-none">{along.error}</p>

  return (
    <div className="all-stops">
      <p className="trip-source">
        {along.total_found?.toLocaleString('en-IN') ?? along.places.length} places found within {along.radius_km ?? 1.5} km of the road. Showing the best few in every 15 km
        {along.partial ? '. Part of the route could not be searched right now' : ''}.
      </p>
      <nav className="bell-tabs" role="tablist" aria-label="Stop types">
        {FILTERS.map((f) => {
          const count = f.kinds ? along.places.filter((p) => f.kinds!.includes(p.kind)).length : along.places.length
          return (
            <button key={f.id} role="tab" aria-selected={filter === f.id} className={filter === f.id ? 'on' : ''} onClick={() => setFilter(f.id)} disabled={!count}>
              {f.label}
              {count > 0 && <i>{count}</i>}
            </button>
          )
        })}
      </nav>
      <ol className="along-list">
        {shown.map((p) => {
          const { label, Icon } = KIND[p.kind]
          return (
            <li key={p.osm} className={p.near_break ? 'near-break' : ''}>
              <time>
                <b>{p.after_min < 1 ? 'Start' : duration(p.after_min)}</b>
                <small>km {Math.round(p.km)}</small>
              </time>
              <Icon size={15} className={`kind-${p.kind}`} />
              <span>
                <b>
                  {p.name} <GoogleRating google={p.google} />
                </b>
                <small>
                  {[
                    label,
                    p.detour_km <= 0.3 ? 'on the route' : `${p.detour_km} km off`,
                    !p.after_overnight && p.after_min >= 1 ? `about ${clock(p.eta)}` : null,
                    p.opening_hours === '24/7' ? 'open 24 hours' : p.opening_hours ? p.opening_hours : null,
                    p.near_break ? (mode === 'bike' ? 'good for your riding break' : 'good for your driving break') : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </small>
              </span>
              <nav>
                {p.phone && (
                  <a href={`tel:${p.phone.split(/[;,]/)[0].replace(/\s/g, '')}`} aria-label={`Call ${p.name}`}>
                    <Phone size={13} />
                  </a>
                )}
                <a href={directionsUrl(p.lat, p.lon)} target="_blank" rel="noreferrer" aria-label={`Directions to ${p.name}`}>
                  <Navigation size={13} />
                </a>
                <a href={p.osm} target="_blank" rel="noreferrer" aria-label={`${p.name} on OpenStreetMap`}>
                  <MapPinned size={13} />
                </a>
              </nav>
            </li>
          )
        })}
      </ol>
      {shown.length === 0 && (
        <p className="rest-none">
          <Coffee size={13} /> Nothing of this type is mapped along the route.
        </p>
      )}
      {rated && <p className="trip-source">Ratings © Google. Places © OpenStreetMap contributors.</p>}
    </div>
  )
}
