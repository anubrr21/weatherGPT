import { BedDouble, Coffee, Fuel, ParkingSquare, Star, UtensilsCrossed } from 'lucide-react'
import type { RestOption } from '../../lib/trip'

export const KIND: Record<RestOption['kind'], { label: string; Icon: typeof Fuel }> = {
  services: { label: 'Highway plaza', Icon: ParkingSquare },
  rest_area: { label: 'Rest area', Icon: ParkingSquare },
  fuel: { label: 'Fuel', Icon: Fuel },
  restaurant: { label: 'Restaurant', Icon: UtensilsCrossed },
  fast_food: { label: 'Quick food', Icon: UtensilsCrossed },
  cafe: { label: 'Tea / café', Icon: Coffee },
  hotel: { label: 'Hotel', Icon: BedDouble },
  motel: { label: 'Motel', Icon: BedDouble },
  guest_house: { label: 'Guest house', Icon: BedDouble },
}

export function GoogleRating({ google }: { google: RestOption['google'] }) {
  if (!google) return null
  const badge = (
    <>
      <Star size={11} /> {google.rating.toFixed(1)}
      <small>({google.count.toLocaleString('en-IN')})</small>
    </>
  )
  return google.url ? (
    <a className="g-rating" href={google.url} target="_blank" rel="noreferrer" title="Rating on Google Maps">
      {badge}
    </a>
  ) : (
    <span className="g-rating">{badge}</span>
  )
}
