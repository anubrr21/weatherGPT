import { Droplets, Flame, Leaf, Sailboat, Sprout, Sun, Train, Waves } from 'lucide-react'
import type { Insight } from '../lib/types'

const ICONS: Record<string, typeof Sun> = {
  spray: Sprout,
  irrigation: Droplets,
  dry: Leaf,
  sea: Sailboat,
  heat: Flame,
  flood: Waves,
  commute: Train,
  day: Sun,
}

export default function InsightStrip({ items, onAsk }: { items: Insight[] | null; onAsk: (kind: string) => void }) {
  if (!items?.length) return null
  return (
    <section className="insights" aria-label="Your briefing">
      {items.map((it) => {
        const Icon = ICONS[it.kind] ?? Sun
        return (
          <button key={it.kind} className={`insight ${it.tone}`} onClick={() => onAsk(it.kind)}>
            <span className="insight-title">
              <Icon size={13} /> {it.title}
            </span>
            <b>{it.value}</b>
            <small>{it.detail}</small>
          </button>
        )
      })}
    </section>
  )
}
