import { LocateFixed, MapPin, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Place } from '../lib/types'

interface Props {
  saved: Place[]
  onPick: (p: Place) => void
  onLocate: () => void
  onClose: () => void
}

export default function LocationSearch({ saved, onPick, onLocate, onClose }: Props) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Place[]>([])
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => inputRef.current?.focus(), [])

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([])
      return
    }
    setLoading(true)
    const id = setTimeout(() => {
      api
        .geocode(q.trim())
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(id)
  }, [q])

  return (
    <div className="search-overlay" role="dialog" aria-modal="true" aria-label="Choose location" onClick={onClose}>
      <div className="search-panel" onClick={(e) => e.stopPropagation()}>
        <div className="search-field">
          <Search size={18} />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'Enter' && results[0]) onPick(results[0])
            }}
            placeholder="Village, town, city or district"
          />
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <button className="search-locate" onClick={onLocate}>
          <LocateFixed size={16} /> Use my current location
        </button>
        <ul className="search-results">
          {loading && <li className="dim">Searching…</li>}
          {(q.trim().length < 2 ? saved : results).map((p) => (
            <li key={`${p.lat},${p.lon}`}>
              <button onClick={() => onPick(p)}>
                <MapPin size={15} />
                <span>
                  <b>{p.name}</b>
                  <small>{[p.district, p.state].filter(Boolean).join(', ')}{p.country_code && p.country_code !== 'IN' ? ` · ${p.country}` : ''}</small>
                </span>
                <em>{p.lat.toFixed(2)}, {p.lon.toFixed(2)}</em>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
