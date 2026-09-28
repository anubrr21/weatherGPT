import { Phone, Plus, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { LANGUAGES } from '../lib/languages'
import { phoneApi, type FamilyPhone, type PhoneStatus } from '../lib/phone'
import type { Place } from '../lib/types'

interface Props {
  places: Place[]
  current: Place | null
}

const keyOf = (p: Place) => `${p.lat.toFixed(3)},${p.lon.toFixed(3)}`

export default function FamilyPhones({ places, current }: Props) {
  const options = useMemo(() => {
    const all = current ? [current, ...places] : places
    return all.filter((p, i) => all.findIndex((q) => keyOf(q) === keyOf(p)) === i)
  }, [places, current])
  const [phones, setPhones] = useState<FamilyPhone[]>([])
  const [status, setStatus] = useState<PhoneStatus | null>(null)
  const [number, setNumber] = useState('')
  const [placeKey, setPlaceKey] = useState('')
  const [language, setLanguage] = useState('hi')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    phoneApi.family().then((r) => setPhones(r.phones)).catch(() => undefined)
    phoneApi.status().then(setStatus).catch(() => undefined)
  }, [])

  const place = options.find((p) => keyOf(p) === placeKey) ?? options[0]
  const digits = number.replace(/\D/g, '').replace(/^(91|0)(?=\d{10}$)/, '')
  const valid = /^[6-9]\d{9}$/.test(digits)

  const add = async () => {
    if (!place || !valid) return
    setBusy(true)
    setMessage(null)
    try {
      const added = await phoneApi.addFamily(digits, place, language)
      setPhones((list) => [...list.filter((p) => p.ref !== added.ref), { ...added, place: place.name, language }])
      setNumber('')
      setMessage(added.confirmed ? 'Already joined. Warnings will reach this phone.' : 'An SMS was sent. They join when they reply YES.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not add this number.')
    } finally {
      setBusy(false)
    }
  }

  const remove = async (ref: string) => {
    await phoneApi.removeFamily(ref).catch(() => undefined)
    setPhones((list) => list.filter((p) => p.ref !== ref))
  }

  return (
    <section className="family-phones">
      <h3>
        <Phone size={14} /> Basic phones in the family
      </h3>
      <p className="hint">
        Parents or grandparents on a keypad phone get official IMD warnings by SMS, and a voice call in their language when a warning is severe. They can also call and press keys for the forecast and farm advice.
      </p>
      <ul className="rows">
        {phones.map((p) => (
          <li key={p.ref}>
            <span className="row-main">
              <Phone size={14} />
              <span>
                <b>{p.phone}</b>
                <small>
                  {[p.place, LANGUAGES.find((l) => l.code === p.language)?.native].filter(Boolean).join(' · ')} · {p.confirmed ? 'joined' : 'waiting for YES'}
                </small>
              </span>
            </span>
            <button className="icon-btn" onClick={() => remove(p.ref)} aria-label={`Remove ${p.phone}`}>
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>
      {options.length === 0 ? (
        <p className="hint">Save a place first, then add a number for it.</p>
      ) : (
        <>
          <div className="add-row">
            <input
              className="phone-input"
              inputMode="tel"
              autoComplete="off"
              placeholder="Mobile number"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              aria-label="Mobile number"
            />
          </div>
          <div className="add-row">
            <select value={place ? keyOf(place) : ''} onChange={(e) => setPlaceKey(e.target.value)} aria-label="Place for warnings">
              {options.map((p) => (
                <option key={keyOf(p)} value={keyOf(p)}>{p.name}</option>
              ))}
            </select>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language">
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.native}</option>
              ))}
            </select>
            <button className="add-btn" disabled={!valid || busy} onClick={add}>
              <Plus size={15} /> {busy ? 'Adding…' : 'Add'}
            </button>
          </div>
        </>
      )}
      {message && <p className="hint">{message}</p>}
      {status?.provider === 'simulator' && (
        <p className="hint">
          SMS and calls run in simulator mode until a telecom provider is connected.{' '}
          <a href="/phone" target="_blank" rel="noreferrer">Open the phone simulator</a>
        </p>
      )}
      {status?.sms_number && <p className="hint">Anyone can also send WEATHER and their PIN code to {status.sms_number}.</p>}
    </section>
  )
}
