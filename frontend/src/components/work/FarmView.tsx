import { Bug, CalendarDays, Droplets, Loader2, MessageSquareText, PawPrint, RefreshCw, Shovel, Sprout, Thermometer } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { savedAgo, withCache } from '../../lib/offline'
import type { Place, Profile } from '../../lib/types'
import { dayName, shortDay, workApi, type FarmTask, type FarmWorkspace } from '../../lib/work'

interface Props {
  place: Place | null
  profile: Profile
  online: boolean
  onAsk: (text: string) => void
  onEditProfile: () => void
}

const RISK_COLORS = ['rgba(255,255,255,0.1)', '#ffc857', '#ff4d6d']
const THI_COLORS = { none: '#5fd39a', mild: '#ffd166', moderate: '#ff9f43', severe: '#ff4d6d' }
const TASK_ORDER: FarmTask['task'][] = ['hazard', 'spray', 'irrigate', 'fertiliser', 'harvest']

const sortTasks = (tasks: FarmTask[]) => [...tasks].sort((a, b) => TASK_ORDER.indexOf(a.task) - TASK_ORDER.indexOf(b.task))
const percent = (v: number) => `${Math.round(v * 100)}%`

export default function FarmView({ place, profile, online, onAsk, onEditProfile }: Props) {
  const [data, setData] = useState<FarmWorkspace | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cropKey = profile.crops.map((c) => `${c.name}:${c.stage ?? ''}`).join(',')

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache(`farm-${cropKey}`, place.lat, place.lon, () => workApi.farm(place.lat, place.lon, profile.crops), online)
      setData(Array.isArray(result.data.plan) ? result.data : null)
      setSavedAt(result.cached ? result.savedAt : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [place?.lat, place?.lon, cropKey, online])

  useEffect(() => {
    load()
  }, [load])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to plan your farm work.</p></div>

  const today = data?.plan[0]
  const water = data?.water
  const maxWater = water ? Math.max(1, ...water.days.map((d) => Math.max(d.need_mm, d.rain_mm))) : 1
  const soil = data?.soil
  const cropLabel = data?.crops.length ? data.crops.map((c) => c.crop).join(', ') : 'your crop'

  return (
    <div className="cy farm">
      <header className="trip-head cy-head">
        <h1>Your farm</h1>
        <p>A day-by-day work plan, disease weather, water and soil for {cropLabel} at {place.name}.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh farm plan">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      <div className="chips farm-crops">
        {profile.crops.map((c) => (
          <span key={c.name} className="farm-crop">
            <Sprout size={13} /> {c.name}
            {c.stage ? ` · ${c.stage}` : ''}
          </span>
        ))}
        <button onClick={onEditProfile}>{profile.crops.length ? 'Change crops or stage' : 'Add your crops for crop-specific advice'}</button>
      </div>

      {loading && !data && <p className="trip-step">Reading the soil and the next seven days…</p>}
      {error && !data && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing the farm plan saved {savedAgo(savedAt)}.</p>}

      {data?.warnings && data.warnings.length > 0 && (
        <section className="cy-official">
          {data.warnings.slice(0, 2).map((w, k) => (
            <article key={k}>
              <em>IMD / NDMA · {w.severity}</em>
              <b>{w.event ?? 'Warning'}</b>
              <p>{w.headline}</p>
            </article>
          ))}
        </section>
      )}

      {data && today && (
        <section className="farm-today">
          <h3>
            <CalendarDays size={15} /> Today in the field
          </h3>
          <div className="farm-today-grid">
            {sortTasks(today.tasks).map((t) => (
              <div key={t.task + t.text} className={`farm-task ${t.status}`}>
                <b>{t.text}</b>
                <small>{t.detail}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {data && (
        <section className="trip-card">
          <h3>
            <CalendarDays size={15} /> Seven-day field plan
          </h3>
          <ul className="farm-plan">
            {data.plan.map((d) => (
              <li key={d.date}>
                <div className="farm-day">
                  <b>{dayName(d.date, data.today)}</b>
                  <small>
                    {d.tmin !== null ? Math.round(d.tmin) : '–'}–{d.tmax !== null ? Math.round(d.tmax) : '–'} °C · {d.rain_mm} mm{d.rain_prob !== null ? ` (${d.rain_prob}%)` : ''} · {d.sunshine_h} h sun
                  </small>
                </div>
                <div className="farm-chips">
                  {sortTasks(d.tasks).map((t) => (
                    <span key={t.task + t.text} className={t.status} title={t.detail}>
                      {t.text}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          <p className="trip-source">Spray rule: {data.spray.rules}.</p>
        </section>
      )}

      {data && data.diseases.length > 0 && (
        <section className="trip-card">
          <h3>
            <Bug size={15} /> Disease weather watch
          </h3>
          <div className="farm-diseases">
            {data.diseases.map((d) => (
              <article key={d.id} className={`risk${d.peak}`}>
                <header>
                  <b>{d.name}</b>
                  <em style={{ background: RISK_COLORS[d.peak], color: d.peak ? '#0b0f16' : 'var(--ink-2)' }}>{d.peak_label}</em>
                </header>
                <div className="farm-strip">
                  {d.days.map((s) => (
                    <span key={s.date} className={`${s.past ? 'past' : ''} ${s.date === data.today ? 'now' : ''}`} title={`${s.date}: ${['low', 'moderate', 'high'][s.level]}`}>
                      <i style={{ background: RISK_COLORS[s.level] }} />
                      <small>{shortDay(s.date).slice(0, 2)}</small>
                    </span>
                  ))}
                </div>
                {d.peak > 0 ? (
                  <p>
                    Weather favours it {d.risky_days.length ? `on ${d.risky_days.map((x) => dayName(x, data.today)).join(', ')}` : 'this week'}: {d.why}. Look for {d.watch_for}.
                  </p>
                ) : (
                  <p className="dim">Weather is not favourable for it this week.</p>
                )}
                <small>{d.source}</small>
              </article>
            ))}
          </div>
          <p className="trip-source">{data.note}</p>
        </section>
      )}

      {water && (
        <section className="trip-card">
          <h3>
            <Droplets size={15} /> Water budget{water.crop ? ` for ${water.crop}` : ''}
          </h3>
          <div className="cy-stats">
            <span>
              <small>Crop needs, 7 days</small>
              <b>{water.need_7d_mm} mm</b>
            </span>
            <span>
              <small>Rain expected</small>
              <b>{water.rain_7d_mm} mm</b>
              <em>{water.effective_7d_mm} mm useful</em>
            </span>
            <span>
              <small>Rain, last 7 days</small>
              <b>{water.rain_last_7d_mm} mm</b>
              <em>{water.rainy_days_last_7d} rainy day{water.rainy_days_last_7d === 1 ? '' : 's'}</em>
            </span>
            <span>
              <small>Irrigate on</small>
              <b>{water.irrigations.length ? water.irrigations.map((d) => dayName(d, data!.today)).join(', ') : 'Not needed'}</b>
            </span>
          </div>
          <div className="farm-water">
            {water.days.map((d) => (
              <span key={d.date} className={d.irrigate ? 'irrigate' : ''} title={`Need ${d.need_mm} mm · rain ${d.rain_mm} mm · shortfall ${d.deficit_mm} mm`}>
                <div>
                  <i className="need" style={{ height: `${(d.need_mm / maxWater) * 100}%` }} />
                  <i className="rain" style={{ height: `${(d.rain_mm / maxWater) * 100}%` }} />
                </div>
                <b>{d.deficit_mm}</b>
                <small>{shortDay(d.date)}</small>
              </span>
            ))}
          </div>
          <div className="lt-key">
            <span>
              <i style={{ background: '#ff9f43' }} /> crop water need
            </span>
            <span>
              <i style={{ background: '#6fb7ff' }} /> rain
            </span>
            <span>number = running shortfall in mm</span>
          </div>
          <p className="trip-source">{water.method}.</p>
        </section>
      )}

      {soil?.now && (
        <section className="trip-card">
          <h3>
            <Shovel size={15} /> Soil
          </h3>
          <div className="cy-stats">
            <span>
              <small>Surface</small>
              <b>{soil.now.temp_surface} °C</b>
            </span>
            <span>
              <small>Seed depth, 6 cm</small>
              <b>{soil.now.temp_6cm} °C</b>
            </span>
            <span>
              <small>Root zone, 18 cm</small>
              <b>{soil.now.temp_18cm} °C</b>
            </span>
          </div>
          <h4 className="trip-sub">Soil moisture (share of soil volume that is water)</h4>
          <div className="farm-moisture">
            {(
              [
                ['Top 3–9 cm', soil.now.moisture_top],
                ['Root zone 9–27 cm', soil.now.moisture_root],
                ['Deep 27–81 cm', soil.now.moisture_deep],
              ] as [string, number][]
            ).map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <i>
                  <b style={{ width: `${Math.min(100, (value / 0.5) * 100)}%` }} />
                </i>
                <em>{percent(value)}</em>
              </div>
            ))}
          </div>
          {soil.sowing.length > 0 && (
            <>
              <h4 className="trip-sub">Sowing: soil at seed depth averages {soil.seed_depth_temp} °C over the next 3 days</h4>
              <ul className="farm-sowing">
                {soil.sowing.map((s) => (
                  <li key={s.crop} className={s.verdict}>
                    <b>{s.crop}</b>
                    <span>{s.text}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="farm-trend">
            {soil.days.map((d) => (
              <span key={d.date} className={`${d.past ? 'past' : ''} ${d.date === data!.today ? 'now' : ''}`} title={`${d.date}: ${d.temp_6cm} °C, root-zone moisture ${percent(d.moisture_root)}`}>
                <i style={{ height: `${Math.min(100, (d.moisture_root / 0.5) * 100)}%` }} />
                <small>{shortDay(d.date).slice(0, 2)}</small>
              </span>
            ))}
          </div>
          <p className="trip-source">Bars: root-zone moisture over the last week and the week ahead. Soil values come from the weather model's land surface, not a sensor in your field.</p>
        </section>
      )}

      {data && data.livestock.length > 0 && (
        <section className="trip-card">
          <h3>
            <PawPrint size={15} /> Cattle and buffalo heat stress
          </h3>
          <div className="farm-thi">
            {data.livestock.map((l) => (
              <span key={l.date} title={`THI ${l.thi}`}>
                <i style={{ background: THI_COLORS[l.level] }} />
                <b>{Math.round(l.thi)}</b>
                <small>{shortDay(l.date)}</small>
              </span>
            ))}
          </div>
          <p>
            <Thermometer size={13} /> Temperature-humidity index at the hottest hour. Below 72 comfortable, 72–78 mild, 79–88 moderate (give shade and extra water, milk yield drops), 89+ severe.
          </p>
        </section>
      )}

      <button
        className="trip-ask"
        onClick={() => onAsk(`I grow ${cropLabel} at ${place.name}. Looking at the next 7 days, what field work should I do each day, when should I spray and irrigate, and which diseases or pests should I watch for?`)}
      >
        <MessageSquareText size={16} /> Ask WeatherGPT about my farm this week
      </button>
      {data && <p className="trip-source">{data.source}.</p>}
    </div>
  )
}
