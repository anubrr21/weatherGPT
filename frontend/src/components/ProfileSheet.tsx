import { BellRing, Gauge, Lock, MapPin, Plus, Send, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import FamilyPhones from './FamilyPhones'
import { CROPS, ROLES, STAGES, addPlace, removePlace } from '../lib/profile'
import type { DataMode } from '../lib/connection'
import { NOTICE_KINDS, sendTestNotice, type NotifyPrefs } from '../lib/notices'
import type { Place, Profile } from '../lib/types'

interface Props {
  profile: Profile
  current: Place | null
  onChange: (p: Profile) => void
  prefs: NotifyPrefs
  onPrefsChange: (p: NotifyPrefs) => void
  dataMode: DataMode
  liteReason: string | null
  onDataMode: (mode: DataMode) => void
  onPickPlace: (p: Place) => void
  onClose: () => void
}

export default function ProfileSheet({ profile, current, onChange, prefs, onPrefsChange, dataMode, liteReason, onDataMode, onPickPlace, onClose }: Props) {
  const [testing, setTesting] = useState<string | null>(null)
  const toggleKind = (kind: NotifyPrefs['kinds'][number]) =>
    onPrefsChange({ ...prefs, kinds: prefs.kinds.includes(kind) ? prefs.kinds.filter((k) => k !== kind) : [...prefs.kinds, kind] })
  const briefingOn = prefs.kinds.includes('briefing') && Boolean(prefs.briefing_at)
  const quietOn = Boolean(prefs.quiet_from && prefs.quiet_to)
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

        <section className="notify-prefs">
          <h3>
            <BellRing size={14} /> Smart notifications
          </h3>
          <p className="hint">Worked out from 15-minute rain nowcasts and hourly forecasts for your saved places, written in your language, for you.</p>
          <div className="chips">
            {NOTICE_KINDS.map((k) => (
              <button
                key={k.kind}
                className={prefs.kinds.includes(k.kind) || k.locked ? 'on' : ''}
                disabled={k.locked}
                onClick={() => toggleKind(k.kind)}
                title={k.hint}
                aria-pressed={prefs.kinds.includes(k.kind) || Boolean(k.locked)}
              >
                {k.locked && <Lock size={11} />} {k.label}
              </button>
            ))}
          </div>
          <div className="time-row">
            <label>
              <span>Morning briefing</span>
              <input
                type="time"
                value={prefs.briefing_at ?? ''}
                disabled={!prefs.kinds.includes('briefing')}
                onChange={(e) => onPrefsChange({ ...prefs, briefing_at: e.target.value || null })}
              />
            </label>
            <label className="switch">
              <input
                type="checkbox"
                checked={quietOn}
                onChange={(e) => onPrefsChange({ ...prefs, quiet_from: e.target.checked ? '22:00' : null, quiet_to: e.target.checked ? '06:00' : null })}
              />
              <span>Quiet hours</span>
            </label>
            {quietOn && (
              <span className="quiet">
                <input type="time" value={prefs.quiet_from ?? ''} onChange={(e) => onPrefsChange({ ...prefs, quiet_from: e.target.value || null })} aria-label="Quiet from" />
                <em>to</em>
                <input type="time" value={prefs.quiet_to ?? ''} onChange={(e) => onPrefsChange({ ...prefs, quiet_to: e.target.value || null })} aria-label="Quiet until" />
              </span>
            )}
          </div>
          <p className="hint">Severe and extreme warnings always come through, even in quiet hours.</p>
          <button
            className="add-btn wide"
            disabled={testing === 'sending' || !briefingOn}
            onClick={async () => {
              setTesting('sending')
              try {
                const result = await sendTestNotice('briefing')
                setTesting(result.created ? 'Sent. Check your notifications.' : result.note ?? 'Nothing to send right now.')
              } catch {
                setTesting('Could not reach WeatherGPT.')
              }
            }}
          >
            <Send size={14} /> {testing === 'sending' ? 'Writing your briefing…' : 'Send me a briefing now'}
          </button>
          {testing && testing !== 'sending' && <p className="hint">{testing}</p>}
        </section>

        <FamilyPhones places={profile.places} current={current} />

        <section className="data-saver">
          <h3>
            <Gauge size={14} /> Data saver
          </h3>
          <div className="chips">
            {(['auto', 'on', 'off'] as DataMode[]).map((mode) => (
              <button key={mode} className={dataMode === mode ? 'on' : ''} onClick={() => onDataMode(mode)}>
                {mode === 'auto' ? 'Automatic' : mode === 'on' ? 'Always on' : 'Off'}
              </button>
            ))}
          </div>
          <p className="hint">
            {dataMode === 'auto'
              ? liteReason
                ? `On right now because ${liteReason}.`
                : 'Switches on by itself on 2G, slow 3G or when your phone saves data.'
              : dataMode === 'on'
                ? 'Sky animation and radar paused, forecasts refresh every 20 minutes, voice replies compressed.'
                : 'Full experience on every connection.'}{' '}
            The last forecast for each place is always kept for offline use.
          </p>
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
