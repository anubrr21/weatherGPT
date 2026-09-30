import { AlertTriangle, CloudLightning, Home, Loader2, MessageSquareText, Radio, RefreshCw, ShieldCheck, Timer, Zap } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { RISK_COLORS, RISK_LABELS, areaCentre, distanceKm, lightningApi, localHeadline, severityColor, type LightningLive, type LightningRisk } from '../../lib/lightning'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place } from '../../lib/types'
import LightningMap from './LightningMap'

interface Props {
  place: Place | null
  online: boolean
  language: string
  onAsk: (text: string) => void
}

const REFRESH_MS = 30000

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : '–'

const dayClock = (iso: string) =>
  new Date(iso).toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })

const issuerName = (issuer: string | null) => (issuer ?? '').replace(/^.*\(/, '').replace(/\)$/, '') || 'Official'

const DOS = [
  'Go inside a pucca building or a closed metal-roof vehicle as soon as you hear thunder.',
  'Stay indoors until 30 minutes after the last thunder.',
  'Unplug electrical appliances; keep away from wired phones, taps, pipes and metal.',
  'If caught in the open with no shelter, crouch low on the balls of your feet with heels together and head tucked in. Do not lie flat.',
  'In a group, spread out at least 15 m apart so one strike does not hurt everyone.',
  'Someone struck by lightning carries no charge. Call 108 or 112 and start CPR at once if they are not breathing.',
]

const DONTS = [
  'Do not shelter under a tree, a tower, an electric pole or a lone hut.',
  'Do not stay in open fields, on rooftops, hilltops, or near water. Fishermen should head to shore at the first thunder.',
  'Do not hold metal tools, umbrellas with metal tips or mobile phones connected to chargers outdoors.',
  'Do not ride bicycles, motorcycles or tractors during a thunderstorm.',
]

export default function LightningView({ place, online, language, onAsk }: Props) {
  const [live, setLive] = useState<LightningLive | null>(null)
  const [risk, setRisk] = useState<LightningRisk | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)
  const [showRisk, setShowRisk] = useState(true)
  const [tick, setTick] = useState(0)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    try {
      const result = await withCache('lightning', place.lat, place.lon, () => lightningApi.live(place.lat, place.lon), online)
      setLive(Array.isArray(result.data.strikes) && Array.isArray(result.data.official) ? result.data : null)
      setSavedAt(result.cached ? result.savedAt : null)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, online])

  useEffect(() => {
    load()
    if (!place) return
    withCache('lightning-risk', place.lat, place.lon, () => lightningApi.risk(place.lat, place.lon), online)
      .then((r) => setRisk(Array.isArray(r.data.grid?.cells) ? r.data : null))
      .catch(() => setRisk(null))
  }, [load])

  useEffect(() => {
    if (!online) return
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') load()
      setTick((t) => t + 1)
    }, REFRESH_MS)
    return () => window.clearInterval(id)
  }, [load, online])

  const here = useMemo(() => (live ? live.official.filter((a) => live.official_here.includes(a.id)) : []), [live])
  const sorted = useMemo(() => {
    if (!live || !place) return []
    return live.official
      .map((area) => ({ area, km: (() => {
        const c = areaCentre(area)
        return c ? distanceKm([place.lat, place.lon], c) : Infinity
      })() }))
      .sort((a, b) => a.km - b.km)
  }, [live, place?.lat, place?.lon])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to see lightning risk.</p></div>

  const nearby = live ? (live.rings_30min['10'] ?? 0) : 0
  const lastNear = live?.last_within_10km_min ?? null
  const safeAt = lastNear !== null && lastNear < 30 ? new Date(Date.now() + (30 - lastNear) * 60000).toISOString() : null
  const outlook = risk?.outlook
  const nextStorm = outlook?.next_storm ?? null
  const status: 'official' | 'near' | 'approaching' | 'calm' = here.length ? 'official' : nearby > 0 ? 'near' : live?.motion?.eta_min ? 'approaching' : 'calm'

  return (
    <div className="cy lt">
      <header className="trip-head cy-head">
        <h1>Lightning</h1>
        <p>Official IMD and state lightning warnings, live strikes and the thunderstorm outlook for {place.name}. Refreshes every 30 seconds.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh lightning data">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {error && !live && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing lightning data saved {savedAgo(savedAt)}. Lightning changes by the minute, so treat this as out of date.</p>}

      {live && (
        <section className={`lt-hero ${status}`} data-tick={tick}>
          {status === 'official' ? <AlertTriangle size={24} /> : status === 'calm' ? <ShieldCheck size={24} /> : <Zap size={24} />}
          <div>
            {status === 'official' && (
              <>
                <b>
                  {place.name} is inside an active {here[0].event?.toLowerCase() ?? 'lightning'} warning until {clock(here[0].expires)}.
                </b>
                <p>{localHeadline(here[0], language) ?? here[0].headline}</p>
                <small>
                  {issuerName(here[0].issuer)} · {here[0].areas.join(', ')}
                </small>
              </>
            )}
            {status === 'near' && live.nearest && (
              <>
                <b>
                  Lightning {live.nearest.km} km {live.nearest.direction} of {place.name}, {live.nearest.minutes_ago} min ago.
                </b>
                <p>
                  {nearby} strike{nearby === 1 ? '' : 's'} within 10 km in the last 30 minutes. Go indoors now.
                </p>
              </>
            )}
            {status === 'approaching' && live.motion && (
              <>
                <b>
                  A thunderstorm {live.motion.centre.km} km away is moving {live.motion.heading} at {live.motion.speed_kmh} km/h.
                </b>
                <p>At this speed it reaches {place.name} in about {live.motion.eta_min} minutes. Finish outdoor work and get under cover.</p>
              </>
            )}
            {status === 'calm' && (
              <>
                <b>No official lightning warning covers {place.name} right now.</b>
                <p>
                  {live.nearest ? `The nearest detected strike was ${live.nearest.km} km ${live.nearest.direction}, ${live.nearest.minutes_ago} min ago.` : `No strikes detected within ${live.radius_km} km in the last hour.`}{' '}
                  {nextStorm ? `Models show thunderstorms becoming likely around ${dayClock(nextStorm)}.` : outlook ? 'Models show no likely thunderstorm here in the next 36 hours.' : ''}
                </p>
              </>
            )}
            {safeAt && (
              <p className="lt-timer">
                <Timer size={14} /> 30-minute rule: stay indoors until {clock(safeAt)} if no more thunder is heard.
              </p>
            )}
          </div>
        </section>
      )}

      {live && (
        <div className="cy-stats lt-stats">
          <span>
            <small>Official warnings in India</small>
            <b>{live.official.length}</b>
          </span>
          <span>
            <small>Strikes within 10 / 20 / 30 km</small>
            <b>
              {live.rings_30min['10'] ?? 0} / {live.rings_30min['20'] ?? 0} / {live.rings_30min['30'] ?? 0}
            </b>
            <em>last 30 min</em>
          </span>
          <span>
            <small>Strikes within {live.radius_km} km</small>
            <b>{live.count}</b>
            <em>last hour</em>
          </span>
          <span>
            <small>Storm movement</small>
            <b>{live.motion ? `${live.motion.heading}, ${live.motion.speed_kmh} km/h` : '–'}</b>
          </span>
        </div>
      )}

      <div className="lt-map-tools chips">
        <label className="switch">
          <input type="checkbox" checked={showRisk} onChange={(e) => setShowRisk(e.target.checked)} />
          <span>Thunderstorm risk, next {risk?.grid.hours ?? 6} h</span>
        </label>
        {focus && (
          <button onClick={() => setFocus(null)}>
            <Home size={13} /> Back to {place.name}
          </button>
        )}
      </div>
      <LightningMap live={live} risk={risk} place={place} focus={focus} showRisk={showRisk} />
      <p className="trip-source lt-feed">
        <Radio size={12} /> {live?.feed.connected ? `Strike feed live, listening for ${live.feed.listening_min} min.` : 'Strike feed reconnecting.'} {live?.feed.source}. Coloured areas are the official warning polygons.
      </p>

      {outlook && (
        <section className="trip-card">
          <h3>
            <CloudLightning size={15} /> Thunderstorm outlook for {place.name}, next 36 h
          </h3>
          <div className="lt-hours">
            {outlook.hours.map((h) => (
              <span key={h.time} title={`${dayClock(h.time)} · ${RISK_LABELS[h.score]} · CAPE ${h.cape} J/kg · rain ${h.rain_prob ?? 0}%`}>
                <i style={{ height: `${12 + h.score * 29}%`, background: h.score ? RISK_COLORS[h.score] : 'rgba(255,255,255,0.12)' }} />
                {new Date(h.time).getUTCMinutes() === 0 && Number(new Date(h.time).toLocaleString('en-IN', { hour: 'numeric', hour12: false, timeZone: 'Asia/Kolkata' })) % 6 === 0 && (
                  <small>{new Date(h.time).toLocaleTimeString('en-IN', { hour: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })}</small>
                )}
              </span>
            ))}
          </div>
          <div className="lt-key">
            {RISK_LABELS.map((label, k) => (
              <span key={label}>
                <i style={{ background: k ? RISK_COLORS[k] : 'rgba(255,255,255,0.18)' }} /> {label}
              </span>
            ))}
          </div>
          <p className="trip-source">{risk?.grid.source}. Instability (CAPE above about 1000 J/kg with a negative lifted index) and forecast thunderstorm codes drive the score.</p>
        </section>
      )}

      {sorted.length > 0 && (
        <section className="trip-card">
          <h3>
            <AlertTriangle size={15} /> Active official thunderstorm and lightning warnings
          </h3>
          <ul className="lt-warnings">
            {sorted.map(({ area, km }) => (
              <li key={area.id}>
                <button className={focus === area.id ? 'on' : ''} onClick={() => setFocus(focus === area.id ? null : area.id)}>
                  <i style={{ background: severityColor(area.severity) }} />
                  <span>
                    <b>
                      {area.event ?? 'Warning'} · {area.areas.join(', ')}
                    </b>
                    <small>
                      {issuerName(area.issuer)} · until {clock(area.expires)}
                      {Number.isFinite(km) ? ` · ${Math.round(km)} km away` : ''}
                    </small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <p className="trip-source">From the NDMA SACHET common alerting feed: IMD nowcasts and state disaster management authorities. Tap one to see its area on the map.</p>
        </section>
      )}

      <section className="trip-card lt-safety">
        <h3>
          <ShieldCheck size={15} /> Staying safe from lightning
        </h3>
        <p className="lt-rule">
          <b>30/30 rule.</b> Count from the flash to the thunder. Under 30 seconds means the storm is within about 10 km: go indoors. Stay in until 30 minutes after the last thunder.
        </p>
        <div className="lt-columns">
          <div>
            <h4 className="trip-sub">Do</h4>
            <ul>
              {DOS.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="trip-sub">Don't</h4>
            <ul>
              {DONTS.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </div>
        </div>
        <p className="trip-source">Based on NDMA guidelines on lightning safety. The IITM Pune "Damini" app also gives official lightning alerts for India.</p>
      </section>

      <button
        className="trip-ask"
        onClick={() =>
          onAsk(
            here.length
              ? `There is an official ${here[0].event?.toLowerCase() ?? 'lightning'} warning for ${place.name} until ${clock(here[0].expires)}. What exactly should I do right now?`
              : `Is it safe to work outdoors in ${place.name} today, or will there be lightning and thunderstorms? When is the risk highest?`,
          )
        }
      >
        <MessageSquareText size={16} /> Ask WeatherGPT about lightning here
      </button>
    </div>
  )
}
