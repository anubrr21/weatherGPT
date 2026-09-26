import { MapPin, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { CROPS, ROLES, STAGES, addPlace, removePlace } from '../lib/profile'
import type { Place, Profile } from '../lib/types'

interface Props {
  profile: Profile
  current: Place | null
  onChange: (p: Profile) => void
  onPickPlace: (p: Place) => void
  onClose: () => void
}

export default function ProfileSheet({ profile, current, onChange, onPickPlace, onClose }: Props) {
  const [crop, setCrop] = useState(CROPS[0])
  const [stage, setStage] = useState('mid')
  const currentSaved = current ? profile.places.some((p) => Math.abs(p.lat - current.lat) < 0.01 && Math.abs(p.lon - current.lon) < 0.01) : true

  return (
    <div className="search-overlay" role="dialog" aria-modal="true" aria-label="Your profile" onClick={onClose}>
      <div className="search-panel profile" onClick={(e) => e.stopPropagation()}>
        <header className="profile-head">
          <h2>You</h2>
          <p>WeatherGPT tailors every answer and the home briefing to this. It stays on this device.</p>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <section>
          <h3>I am a…</h3>
          <div className="chips">
            {ROLES.map((r) => (
              <button key={r.id} className={profile.role === r.id ? 'on' : ''} onClick={() => onChange({ ...profile, role: r.id })}>
                {r.label}
              </button>
            ))}
          </div>
        </section>

        {(profile.role === 'farmer' || profile.crops.length > 0) && (
          <section>
            <h3>My crops</h3>
            <ul className="rows">
              {profile.crops.map((c) => (
                <li key={c.name}>
                  <b>{c.name}</b>
                  <select
                    value={c.stage ?? ''}
                    onChange={(e) => onChange({ ...profile, crops: profile.crops.map((x) => (x.name === c.name ? { ...x, stage: e.target.value || null } : x)) })}
                    aria-label={`${c.name} stage`}
                  >
                    <option value="">stage?</option>
                    {STAGES.map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                  <button className="icon-btn" onClick={() => onChange({ ...profile, crops: profile.crops.filter((x) => x.name !== c.name) })} aria-label={`Remove ${c.name}`}>
                    <Trash2 size={15} />
                  </button>
                </li>
              ))}
            </ul>
            <div className="add-row">
              <select value={crop} onChange={(e) => setCrop(e.target.value)} aria-label="Crop">
                {CROPS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Stage">
                {STAGES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <button
                className="add-btn"
                onClick={() => onChange({ ...profile, crops: [...profile.crops.filter((x) => x.name !== crop), { name: crop, stage }] })}
              >
                <Plus size={15} /> Add
              </button>
            </div>
          </section>
        )}

        <section>
          <h3>Saved places</h3>
          <ul className="rows">
            {profile.places.map((p) => (
              <li key={`${p.lat},${p.lon}`}>
                <button className="row-main" onClick={() => onPickPlace(p)}>
                  <MapPin size={14} />
                  <span>
                    <b>{p.name}</b>
                    <small>{[p.district, p.state].filter(Boolean).join(', ')}</small>
                  </span>
                </button>
                <button className="icon-btn" onClick={() => onChange(removePlace(profile, p))} aria-label={`Remove ${p.name}`}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
            {profile.places.length === 0 && <li className="dim">No saved places yet.</li>}
          </ul>
          {current && !currentSaved && (
            <button className="add-btn wide" onClick={() => onChange(addPlace(profile, current))}>
              <Plus size={15} /> Save {current.name}
            </button>
          )}
        </section>

        {profile.notes.length > 0 && (
          <section>
            <h3>Things WeatherGPT remembers</h3>
            <ul className="rows">
              {profile.notes.map((n) => (
                <li key={n}>
                  <span className="note">{n}</span>
                  <button className="icon-btn" onClick={() => onChange({ ...profile, notes: profile.notes.filter((x) => x !== n) })} aria-label="Forget">
                    <Trash2 size={15} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
