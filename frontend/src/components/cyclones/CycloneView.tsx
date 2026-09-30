import { CloudRainWind, ExternalLink, History, Loader2, MapPin, MessageSquareText, Navigation, Phone, RefreshCw, ShieldCheck, Tornado, Waves } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  GRADE_TABLE,
  MONTHS,
  STAGES,
  cycloneApi,
  gradeColor,
  ist,
  stormLabel,
  type CycloneHistory,
  type CycloneLive,
  type LiveStorm,
  type LocalWinds,
  type Shelters,
} from '../../lib/cyclones'
import { savedAgo, withCache } from '../../lib/offline'
import { directionsUrl } from '../../lib/trip'
import type { Place } from '../../lib/types'
import CycloneMap, { type HistoryTrack } from './CycloneMap'

interface Props {
  place: Place | null
  online: boolean
  onAsk: (text: string) => void
}

const RADII = [100, 150, 250]

function Badge({ level, children }: { level: number | null | undefined; children: React.ReactNode }) {
  return (
    <em className="cy-badge" style={{ background: gradeColor(level), color: (level ?? 0) <= 4 ? '#0b0f16' : '#fff' }}>
      {children}
    </em>
  )
}

function Bars({ values, labels, highlight, color }: { values: number[]; labels: string[]; highlight?: number; color?: string }) {
  const top = Math.max(1, ...values)
  return (
    <div className="cy-bars">
      {values.map((v, k) => (
        <span key={k} className={k === highlight ? 'now' : ''} title={`${labels[k]}: ${v}`}>
          <b>{v || ''}</b>
          <i style={{ height: `${(v / top) * 100}%`, background: color }} />
          <small>{labels[k]}</small>
        </span>
      ))}
    </div>
  )
}

function WindChart({ local }: { local: LocalWinds }) {
  const hours = local.hours
  if (hours.length < 2) return null
  const width = 600
  const height = 130
  const maxGust = Math.max(60, ...hours.map((h) => h.gust ?? 0))
  const maxRain = Math.max(5, ...hours.map((h) => h.rain ?? 0))
  const x = (k: number) => (k / (hours.length - 1)) * width
  const gustPath = hours.map((h, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${(height - ((h.gust ?? 0) / maxGust) * (height - 16)).toFixed(1)}`).join(' ')
  return (
    <svg className="cy-chart" viewBox={`0 0 ${width} ${height + 18}`} preserveAspectRatio="none" role="img" aria-label="Wind gusts and rain for the next days">
      {[62, 89].filter((v) => v < maxGust).map((v) => (
        <g key={v}>
          <line x1="0" x2={width} y1={height - (v / maxGust) * (height - 16)} y2={height - (v / maxGust) * (height - 16)} className="cy-chart-rule" />
          <text x="4" y={height - (v / maxGust) * (height - 16) - 3} className="cy-chart-note">{v === 62 ? 'gale 62 km/h' : 'storm 89 km/h'}</text>
        </g>
      ))}
      {hours.map((h, k) => {
        const barHeight = ((h.rain ?? 0) / maxRain) * (height * 0.5)
        return <rect key={k} x={x(k) - 3} y={height - barHeight} width="6" height={barHeight} className="cy-chart-rain" />
      })}
      <path d={gustPath} className="cy-chart-gust" />
      {hours.map((h, k) =>
        new Date(h.time).getUTCHours() === 18 ? (
          <text key={k} x={x(k)} y={height + 14} className="cy-chart-day" textAnchor="middle">
            {new Date(h.time).toLocaleDateString('en-IN', { weekday: 'short', timeZone: 'Asia/Kolkata' })}
          </text>
        ) : null,
      )}
    </svg>
  )
}

function StormCard({ storm, place, focused, onFocus }: { storm: LiveStorm; place: Place | null; focused: boolean; onFocus: () => void }) {
  const hit = storm.impact
  const g = storm.now.grade
  return (
    <article className={`cy-storm ${storm.current ? 'live' : ''} ${focused ? 'on' : ''}`} onClick={onFocus}>
      <header>
        <Tornado size={18} />
        <span>
          <b>{stormLabel(storm.name, storm.start, storm.peak)}</b>
          <small>
            {storm.current ? `Advisory ${ist(storm.issued ?? storm.now.time)}` : `${storm.start ? ist(storm.start) : ''} – ${storm.end ? ist(storm.end) : ''}`} · {storm.source}
          </small>
        </span>
        {g && <Badge level={g.level}>{g.code}</Badge>}
      </header>
      <div className="cy-stats">
        <span>
          <small>{storm.current ? 'Now' : 'Peak'}</small>
          <b>{(storm.current ? g : storm.peak)?.label ?? '–'}</b>
        </span>
        <span>
          <small>Wind</small>
          <b>{(storm.current ? g : storm.peak)?.kmh ?? '–'} km/h</b>
        </span>
        {storm.now.pressure ? (
          <span>
            <small>Pressure</small>
            <b>{storm.now.pressure} hPa</b>
          </span>
        ) : null}
        {storm.surge && (
          <span>
            <small>Surge (model)</small>
            <b>{storm.surge.max_m} m</b>
          </span>
        )}
      </div>
      {hit && place && (
        <div className="cy-impact">
          {storm.current && (
            <p>
              <Navigation size={13} /> {hit.distance_now_km.toLocaleString('en-IN')} km {hit.direction_now} of {place.name}
            </p>
          )}
          {hit.closest && (
            <p>
              <MapPin size={13} /> {storm.current ? (hit.closest.forecast ? 'Forecast to pass' : 'Passed') : 'Passed'} about <b>{hit.closest.km} km</b> {hit.closest.direction} of {place.name}, {ist(hit.closest.time)}
              {hit.closest.grade ? ` as a ${hit.closest.grade.label.toLowerCase()}` : ''}
            </p>
          )}
          {hit.in_cone && <p className="warn">{place.name} is inside the forecast cone of uncertainty.</p>}
          {hit.wind_zone && (
            <p className="warn">
              In the {hit.wind_zone.kmh}+ km/h wind zone{hit.first_gale ? ` from ${ist(hit.first_gale)}` : ''}.
            </p>
          )}
          {hit.stage && (
            <p className={`cy-stage ${hit.stage.code}`}>
              {hit.stage.label} stage for this lead time (about {hit.stage.lead_hours} h). IMD declares the official stage; follow the district administration.
            </p>
          )}
        </div>
      )}
      {storm.now.population_gale ? <p className="cy-pop">About {(storm.now.population_gale / 1e6).toFixed(1)} million people were inside the gale-force wind zone at the last advisory (GDACS).</p> : null}
      {storm.report && (
        <a className="cy-link" href={storm.report} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
          GDACS impact report <ExternalLink size={12} />
        </a>
      )}
    </article>
  )
}

export default function CycloneView({ place, online, onAsk }: Props) {
  const [live, setLive] = useState<CycloneLive | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [history, setHistory] = useState<CycloneHistory | null>(null)
  const [local, setLocal] = useState<LocalWinds | null>(null)
  const [shelters, setShelters] = useState<Shelters | null>(null)
  const [radius, setRadius] = useState(150)
  const [focus, setFocus] = useState<string | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [allTracks, setAllTracks] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!place) return
    setLoading(true)
    setError(null)
    try {
      const result = await withCache('cyclones', place.lat, place.lon, () => cycloneApi.live(place.lat, place.lon), online)
      setLive(result.data)
      setSavedAt(result.cached ? result.savedAt : null)
      setFocus((f) => f ?? result.data.active[0]?.id ?? null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
    cycloneApi.local(place.lat, place.lon).then((r) => setLocal(Array.isArray(r.hours) ? r : null)).catch(() => setLocal(null))
    cycloneApi.shelters(place.lat, place.lon).then((r) => setShelters(Array.isArray(r.designated) && Array.isArray(r.public) ? r : null)).catch(() => setShelters(null))
  }, [place?.lat, place?.lon, online])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!place) return
    withCache(`cyclone-history-${radius}`, place.lat, place.lon, () => cycloneApi.history(place.lat, place.lon, radius), online)
      .then((r) => setHistory(Array.isArray(r.data.storms) || !r.data.available ? r.data : null))
      .catch(() => setHistory(null))
  }, [place?.lat, place?.lon, radius, online])

  const mapStorms = useMemo(() => {
    if (!live) return []
    const recentFocus = live.recent.find((s) => s.id === focus)
    return [...live.active, ...(recentFocus ? [recentFocus] : [])]
  }, [live, focus])

  const tracks = useMemo<HistoryTrack[]>(() => {
    if (!history) return []
    const names = new Map(history.storms.map((s) => [s.sid, `${stormLabel(s.name, s.start, s.peak)} ${s.season} · closest ${s.closest_km} km`]))
    return Object.entries(history.tracks)
      .filter(([sid]) => allTracks || sid === picked)
      .map(([sid, points]) => ({ sid, label: names.get(sid) ?? sid, points, highlight: sid === picked }))
  }, [history, picked, allTracks])

  const month = new Date().getMonth()
  const clim = live?.climatology
  const bayThisMonth = clim?.per_month['Bay of Bengal']?.[month] ?? 0
  const seaThisMonth = clim?.per_month['Arabian Sea']?.[month] ?? 0
  const special = live?.outlook.imd.special
  const jtwc = live?.outlook.jtwc
  const pickStorm = useCallback((id: string) => {
    setFocus(id)
    setPicked(null)
  }, [])
  const mapShelters = useMemo(() => (shelters ? [...shelters.designated, ...shelters.public.slice(0, 8)] : []), [shelters])

  if (!place) return <div className="cy"><p className="trip-step">Pick a place to see cyclone risk.</p></div>

  return (
    <div className="cy">
      <header className="trip-head cy-head">
        <h1>Cyclones</h1>
        <p>Bay of Bengal and Arabian Sea, live from IMD, JTWC and GDACS, with {place.name}'s cyclone history since 1980.</p>
        <button className="icon-btn glass" onClick={load} disabled={loading || !online} aria-label="Refresh cyclone data">
          {loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
        </button>
      </header>

      {error && !live && <p className="trip-error">{error}</p>}
      {savedAt && <p className="trip-saved">Showing cyclone data saved {savedAgo(savedAt)}. {online ? 'Refresh for the latest.' : 'You are offline.'}</p>}

      {live && live.official && live.official.length > 0 && (
        <section className="cy-official">
          {live.official.map((a) => (
            <article key={a.id}>
              <em>IMD / NDMA · {a.severity}</em>
              <b>{a.event ?? 'Cyclone warning'}</b>
              <p>{a.headline}</p>
              {a.instruction && <small>{a.instruction}</small>}
            </article>
          ))}
        </section>
      )}

      {live && live.active.length === 0 && (
        <section className="cy-calm">
          <ShieldCheck size={22} />
          <div>
            <b>No cyclone or depression over the Bay of Bengal or Arabian Sea right now.</b>
            <p>
              {jtwc?.available && jtwc.quiet ? 'JTWC reports no tropical cyclone or disturbance in the North Indian Ocean' : jtwc?.sections?.disturbances && !jtwc.quiet ? `JTWC: ${jtwc.sections.disturbances}` : 'Outlook unavailable'}
              {jtwc?.valid_until ? ` (outlook valid until ${ist(jtwc.valid_until)})` : ''}. {special?.nil ? 'IMD RSMC New Delhi has no special tropical weather bulletin in force.' : ''}
            </p>
            {clim && (
              <p className="dim">
                {MONTHS[month]} climatology since {clim.since}: {bayThisMonth} cyclonic storms formed over the Bay of Bengal and {seaThisMonth} over the Arabian Sea in {MONTHS[month]}, about{' '}
                {((bayThisMonth + seaThisMonth) / clim.seasons).toFixed(1)} a year. WeatherGPT checks every 15 minutes and will alert you automatically.
              </p>
            )}
            <small>Checked {ist(live.fetched)}</small>
          </div>
        </section>
      )}

      {special && !special.nil && special.text && (
        <section className="trip-card cy-bulletin">
          <h3>
            <CloudRainWind size={15} /> IMD RSMC New Delhi special bulletin{special.issued ? ` · ${ist(special.issued)}` : ''}
          </h3>
          <pre>{special.text}</pre>
          <a className="cy-link" href={special.url} target="_blank" rel="noreferrer">
            Open the official PDF <ExternalLink size={12} />
          </a>
        </section>
      )}

      {live && live.active.map((storm) => <StormCard key={storm.id} storm={storm} place={place} focused={focus === storm.id} onFocus={() => pickStorm(storm.id)} />)}

      <CycloneMap storms={mapStorms} focus={focus} history={tracks} place={place} shelters={mapShelters} onPickStorm={pickStorm} />

      {live && live.recent.length > 0 && (
        <section className="trip-card">
          <h3>
            <Tornado size={15} /> Recent systems (last 5 months)
          </h3>
          <div className="cy-recent">
            {live.recent.map((storm) => (
              <StormCard key={storm.id} storm={storm} place={place} focused={focus === storm.id} onFocus={() => (focus === storm.id ? setFocus(null) : pickStorm(storm.id))} />
            ))}
          </div>
        </section>
      )}

      {local && (
        <section className="trip-card">
          <h3>
            <Waves size={15} /> Wind and rain at {place.name}, next 3½ days
          </h3>
          <div className="cy-stats">
            <span>
              <small>Strongest gust</small>
              <b>{local.max_gust ? `${local.max_gust.kmh} km/h` : '–'}</b>
              {local.max_gust && <em>{ist(local.max_gust.time)}</em>}
            </span>
            <span>
              <small>Rain, 72 h</small>
              <b>{local.rain_72h_mm} mm</b>
            </span>
            <span>
              <small>Lowest pressure</small>
              <b>{local.min_pressure ? `${local.min_pressure.hpa} hPa` : '–'}</b>
            </span>
          </div>
          <WindChart local={local} />
          <p className="trip-source">
            Line: gusts (km/h). Bars: rain per hour. {local.source}.
          </p>
        </section>
      )}

      {history && history.available && (
        <section className="trip-card">
          <h3>
            <History size={15} /> Cyclones near {place.name} since {history.since}
          </h3>
          <div className="chips cy-radius">
            {RADII.map((r) => (
              <button key={r} className={radius === r ? 'on' : ''} onClick={() => setRadius(r)}>
                within {r} km
              </button>
            ))}
            <label className="switch">
              <input type="checkbox" checked={allTracks} onChange={(e) => setAllTracks(e.target.checked)} />
              <span>Show tracks on map</span>
            </label>
          </div>
          <div className="cy-stats">
            <span>
              <small>Systems</small>
              <b>{history.count}</b>
            </span>
            <span>
              <small>Cyclonic storm or stronger here</small>
              <b>{history.cyclonic_storms}</b>
            </span>
            <span>
              <small>Peaked severe or stronger</small>
              <b>{history.severe_or_worse}</b>
            </span>
            <span>
              <small>Landfalls within {history.radius_km} km</small>
              <b>{history.landfalls}</b>
            </span>
          </div>
          {history.return_period_years ? (
            <p>
              A cyclonic storm passes within {history.radius_km} km of {place.name} about <b>once every {history.return_period_years} years</b>.
            </p>
          ) : (
            <p>No cyclonic storm has passed within {history.radius_km} km of {place.name} since {history.since}.</p>
          )}
          {history.count > 0 && (
            <>
              <h4 className="trip-sub">By month of closest approach</h4>
              <Bars values={history.by_month} labels={MONTHS} highlight={month} />
              <h4 className="trip-sub">Storms that came closest to you</h4>
              <ul className="cy-history">
                {history.storms.slice(0, 25).map((s) => (
                  <li key={s.sid}>
                    <button className={picked === s.sid ? 'on' : ''} onClick={() => setPicked(picked === s.sid ? null : s.sid)}>
                      <Badge level={s.at_closest?.level}>{s.at_closest?.code ?? '–'}</Badge>
                      <span>
                        <b>{s.name ? `${s.name} · ${s.season}` : stormLabel(null, s.start, s.peak)}</b>
                        <small>
                          {s.closest_km} km {s.direction} · {new Date(s.closest_time).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' })} · peak {s.peak?.label ?? '–'}
                          {s.landfall_km !== null && s.landfall_km <= history.radius_km ? ` · landfall ${s.landfall_km} km away` : ''}
                        </small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="trip-source">{history.source}. Winds are IMD 3-minute averages where IMD reported them, otherwise converted from JTWC 1-minute winds.</p>
        </section>
      )}

      {clim && (
        <section className="trip-card">
          <h3>
            <CloudRainWind size={15} /> When cyclones form in the North Indian Ocean
          </h3>
          <h4 className="trip-sub">Bay of Bengal</h4>
          <Bars values={clim.per_month['Bay of Bengal']} labels={MONTHS} highlight={month} color="#ff9f43" />
          <h4 className="trip-sub">Arabian Sea</h4>
          <Bars values={clim.per_month['Arabian Sea']} labels={MONTHS} highlight={month} color="#6fb7ff" />
          <p className="trip-source">
            {clim.note}, {clim.since}–{clim.since !== null ? clim.since + clim.seasons - 1 : ''}. Two seasons: April–June before the monsoon and October–December after it.
          </p>
        </section>
      )}

      {shelters && (
        <section className="trip-card">
          <h3>
            <ShieldCheck size={15} /> Shelters near {place.name}
          </h3>
          {shelters.designated.length > 0 ? (
            <ul className="cy-shelters">
              {shelters.designated.map((s) => (
                <li key={s.osm}>
                  <span>
                    <b>{s.name ?? s.label}</b>
                    <small>
                      {s.label} · {s.km} km{s.capacity ? ` · capacity ${s.capacity}` : ''}
                    </small>
                  </span>
                  <a href={directionsUrl(s.lat, s.lon)} target="_blank" rel="noreferrer" aria-label={`Directions to ${s.name ?? s.label}`}>
                    <Navigation size={14} />
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rest-none">No designated cyclone shelter is mapped within {shelters.radius_km} km in OpenStreetMap.</p>
          )}
          {shelters.public.length > 0 && (
            <>
              <h4 className="trip-sub">Schools and halls often opened as relief camps</h4>
              <ul className="cy-shelters">
                {shelters.public.slice(0, 8).map((s) => (
                  <li key={s.osm}>
                    <span>
                      <b>{s.name ?? s.label}</b>
                      <small>
                        {s.label} · {s.km} km
                      </small>
                    </span>
                    <a href={directionsUrl(s.lat, s.lon)} target="_blank" rel="noreferrer" aria-label={`Directions to ${s.name ?? s.label}`}>
                      <Navigation size={14} />
                    </a>
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="cy-helplines">
            {shelters.helplines.map((h) => (
              <a key={h.number} href={`tel:${h.number}`}>
                <Phone size={13} /> <b>{h.number}</b> {h.label}
              </a>
            ))}
          </div>
          <p className="trip-source">{shelters.note}</p>
        </section>
      )}

      <section className="trip-card">
        <h3>IMD's four-stage cyclone warning</h3>
        <ol className="cy-steps">
          {STAGES.map((s) => (
            <li key={s.code}>
              <b>{s.label}</b>
              <small>{s.when}</small>
              <p>{s.what}</p>
            </li>
          ))}
        </ol>
        <h4 className="trip-sub">IMD intensity scale (3-minute sustained wind)</h4>
        <table className="cy-table">
          <tbody>
            {GRADE_TABLE.map((g, k) => (
              <tr key={g.code}>
                <td>
                  <Badge level={k + 1}>{g.code}</Badge>
                </td>
                <td>{g.label}</td>
                <td>{g.kmh} km/h</td>
                <td>{g.kt} kt</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <button
        className="trip-ask"
        onClick={() =>
          onAsk(
            live && live.active.length
              ? `Is ${stormLabel(live.active[0].name, live.active[0].start, live.active[0].now.grade)} a threat to ${place.name}? When will it be closest, how strong will the wind and rain be, and what should I do now?`
              : `How exposed is ${place.name} to cyclones? Which past cyclones hit near here, which months are riskiest, and how should my family prepare before the season?`,
          )
        }
      >
        <MessageSquareText size={16} /> Ask WeatherGPT about cyclones here
      </button>

      <p className="trip-source">
        Live: GDACS (JTWC advisories, ECMWF/GFS storm surge), JTWC Indian Ocean outlook, IMD RSMC New Delhi bulletins and SACHET CAP warnings. History: IBTrACS v04r01. Shelters: OpenStreetMap. The official stage and
        evacuation orders come from IMD and your district administration.
      </p>
    </div>
  )
}
