import { createContext, useContext } from 'react'
import type { Place } from './types'

export interface PlaceControl {
  current: Place | null
  focus: (place: Place) => void
}

export const PlaceContext = createContext<PlaceControl>({ current: null, focus: () => undefined })

export const usePlaceControl = () => useContext(PlaceContext)

export const samePlace = (a: Place | null | undefined, b: Place | null | undefined) =>
  Boolean(a && b && Math.abs(a.lat - b.lat) < 0.05 && Math.abs(a.lon - b.lon) < 0.05)
