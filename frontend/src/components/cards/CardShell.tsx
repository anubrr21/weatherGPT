import { MapPinned } from 'lucide-react'
import type { ReactNode } from 'react'
import { samePlace, usePlaceControl } from '../../lib/placeContext'
import type { Place } from '../../lib/types'

interface Props {
  title: string
  meta?: string
  tone?: string
  place?: Place
  children: ReactNode
}

export default function CardShell({ title, meta, tone, place, children }: Props) {
  const { current, focus } = usePlaceControl()
  const elsewhere = place && typeof place.lat === 'number' && !samePlace(place, current)
  return (
    <section className={`card ${tone ? `card-${tone}` : ''}`}>
      <header className="card-head">
        <h3>{title}</h3>
        {meta && <span>{meta}</span>}
      </header>
      {children}
      {elsewhere && (
        <button className="card-focus" onClick={() => focus(place)}>
          <MapPinned size={13} /> Show {place.name} on home
        </button>
      )}
    </section>
  )
}
