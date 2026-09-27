import { LocateFixed, MapPin, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import type { Place } from '../../lib/types'

interface Props {
  label: string
  value: Place | null
  onChange: (place: Place | null) => void
  current?: Place | null
  autoFocus?: boolean
}

export default function PlaceInput({ label, value, onChange, current, autoFocus }: Props) {
  const [text, setText] = useState(value?.name ?? '')
  const [results, setResults] = useState<Place[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => setText(value?.name ?? ''), [value?.lat, value?.lon, value?.name])

  useEffect(() => {
    if (!open || text.trim().length < 2 || text === value?.name) {
      setResults([])
      return
    }
    setLoading(true)
    const id = setTimeout(() => {
      api
        .geocode(text.trim())
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(id)
  }, [text, open])

  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  const pick = (p: Place) => {
    onChange(p)
    setText(p.name)
    setOpen(false)
  }

  return (
    <div className="trip-place" ref={box}>
      <label>
        <span>{label}</span>
        <input
          value={text}
          autoFocus={autoFocus}
          placeholder="Village, town, city or airport"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
            if (value) onChange(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && results[0]) pick(results[0])
            if (e.key === 'Escape') setOpen(false)
          }}
        />
        {text && (
          <button
            className="icon-btn"
            aria-label={`Clear ${label}`}
            onClick={() => {
              setText('')
              onChange(null)
              setOpen(true)
            }}
          >
            <X size={14} />
          </button>
        )}
      </label>
      {open && (results.length > 0 || loading || (current && !value)) && (
        <ul className="trip-suggest">
          {current && !value && text.trim().length < 2 && (
            <li>
              <button onClick={() => pick(current)}>
                <LocateFixed size={14} />
                <span>
                  <b>{current.name}</b>
                  <small>Place on your home screen</small>
                </span>
              </button>
            </li>
          )}
          {loading && <li className="dim">Searching…</li>}
          {results.map((p) => (
            <li key={`${p.lat},${p.lon}`}>
              <button onClick={() => pick(p)}>
                <MapPin size={14} />
                <span>
                  <b>{p.name}</b>
                  <small>{[p.district, p.state].filter(Boolean).join(', ')}</small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
