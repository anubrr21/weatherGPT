import { Radar, WifiOff } from 'lucide-react'
import { useState } from 'react'
import type { Place } from '../lib/types'
import RadarMap from './RadarMap'

export default function RadarGate({ place, lite, online }: { place: Place; lite: boolean; online: boolean }) {
  const [wanted, setWanted] = useState(false)
  if (online && (!lite || wanted)) return <RadarMap place={place} />
  return (
    <section className="radar radar-gate" aria-label="Live rain map">
      {online ? (
        <button className="radar-load" onClick={() => setWanted(true)}>
          <Radar size={18} />
          <span>
            <b>Load live radar</b>
            <small>Paused to save data. Animated radar uses about 1–2 MB.</small>
          </span>
        </button>
      ) : (
        <p className="radar-offline">
          <WifiOff size={16} /> Live radar needs a connection. It will come back when you are online.
        </p>
      )}
    </section>
  )
}
