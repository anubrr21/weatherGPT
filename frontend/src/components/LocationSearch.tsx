import { Bookmark, BookmarkCheck, LocateFixed, MapPin, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Place } from '../lib/types'

interface Props {
  saved: Place[]
  current: Place | null
  onToggleSave: (p: Place) => void
  onPick: (p: Place) => void
  onLocate: () => void
  onClose: () => void
}

const same = (a: Place, b: Place) => Math.abs(a.lat - b.lat) < 0.01 && Math.abs(a.lon - b.lon) < 0.01

export default function LocationSearch({ saved, current, onToggleSave, onPick, onLocate, onClose }: Props) {
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

  const browsing = q.trim().length < 2
  const isSaved = (p: Place) => saved.some((x) => same(x, p))

  const row = (p: Place) => {
    const on = isSaved(p)
    return (
      <li key={`${p.lat},${p.lon}`} className="search-row">
        <button className="search-pick" onClick={() => onPick(p)}>
          <MapPin size={15} />
          <span>
            <b>{p.name}</b>
            <small>{[p.district, p.state].filter(Boolean).join(', ')}{p.country_code && p.country_code !== 'IN' ? ` · ${p.country}` : ''}</small>
          </span>
          <em>{p.lat.toFixed(2)}, {p.lon.toFixed(2)}</em>
        </button>
        <button
          className={`search-save ${on ? 'on' : ''}`}
          onClick={() => onToggleSave(p)}
          aria-pressed={on}
          aria-label={on ? `Remove ${p.name} from saved places` : `Save ${p.name}`}
          title={on ? 'Saved · tap to remove' : 'Save place'}
        >
          {on ? <BookmarkCheck size={17} /> : <Bookmark size={17} />}
        </button>
      </li>
    )
  }

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
          {browsing && current && !isSaved(current) && (
            <>
              <li className="search-label">Current place</li>
              {row(current)}
            </>
          )}
          {browsing && <li className="search-label">Saved places{saved.length ? ` · ${saved.length}` : ''}</li>}
          {browsing && !saved.length && <li className="dim">Search any village, town or city and tap the bookmark to save it here.</li>}
          {(browsing ? saved : results).map(row)}
          {!browsing && !loading && !results.length && <li className="dim">No places found.</li>}
        </ul>
      </div>
    </div>
  )
}
