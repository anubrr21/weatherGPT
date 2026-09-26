import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Pause, Play, Radar, Satellite } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Place } from '../lib/types'

type Mode = 'radar' | 'satellite'

interface Frame {
  time: number
  url: string
}

interface Source {
  frames: Frame[]
  maxNativeZoom: number
  credit: string
}

const API = import.meta.env.VITE_API_BASE ?? ''
const RAINVIEWER = 'https://api.rainviewer.com/public/weather-maps.json'
const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

const NOTES: Record<Mode, string> = {
  radar: 'Ground radar, last 2 hours. Coverage over India is partial — an empty area does not always mean no rain.',
  satellite: 'NASA GPM IMERG satellite rain estimate. Covers all of India, but runs a few hours behind real time.',
}

async function loadRadar(): Promise<Source> {
  const data = (await fetch(RAINVIEWER).then((r) => r.json())) as { host: string; radar: { past: { time: number; path: string }[]; nowcast?: { time: number; path: string }[] } }
  return {
    frames: [...data.radar.past, ...(data.radar.nowcast ?? [])].map((f) => ({ time: f.time, url: `${data.host}${f.path}/256/{z}/{x}/{y}/4/1_1.png` })),
    maxNativeZoom: 7,
    credit: 'RainViewer',
  }
}

async function loadSatellite(): Promise<Source> {
  const response = await fetch(`${API}/api/satellite/rain`)
  if (!response.ok) throw new Error('satellite feed unavailable')
  const data = (await response.json()) as { max_zoom: number; frames: { time: string; url: string }[] }
  return {
    frames: data.frames.map((f) => ({ time: Date.parse(f.time) / 1000, url: f.url })),
    maxNativeZoom: data.max_zoom,
    credit: 'NASA GIBS / GPM IMERG',
  }
}

function age(time: number) {
  const minutes = Math.round((Date.now() / 1000 - time) / 60)
  if (minutes <= 5) return 'latest'
  if (minutes < 120) return `${minutes} min ago`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min ago`
}

export default function RadarMap({ place }: { place: Place }) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.CircleMarker | null>(null)
  const layersRef = useRef<L.TileLayer[]>([])
  const [mode, setMode] = useState<Mode>('radar')
  const [source, setSource] = useState<Source | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 3, maxZoom: 9 }).setView([place.lat, place.lon], 6)
    L.tileLayer(BASEMAP, {
      maxZoom: 9,
      className: 'radar-basemap',
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    mapRef.current = map
    markerRef.current = L.circleMarker([place.lat, place.lon], { radius: 7, color: '#ffb35c', weight: 3, fillColor: '#ff6a3d', fillOpacity: 0.9 }).addTo(map)
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    mapRef.current?.setView([place.lat, place.lon], mapRef.current.getZoom())
    markerRef.current?.setLatLng([place.lat, place.lon])
  }, [place.lat, place.lon])

  useEffect(() => {
    let cancelled = false
    const load = () =>
      (mode === 'radar' ? loadRadar() : loadSatellite())
        .then((next) => {
          if (cancelled) return
          setSource(next)
          setIndex(next.frames.length - 1)
          setError(null)
        })
        .catch(() => !cancelled && setError(mode === 'radar' ? 'Radar feed unavailable right now' : 'NASA satellite feed unavailable right now'))
    setSource(null)
    load()
    const id = setInterval(load, 10 * 60 * 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [mode])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !source) return
    const attribution = `${mode === 'radar' ? 'Radar' : 'Rain'} © ${source.credit}`
    layersRef.current = source.frames.map((frame) =>
      L.tileLayer(frame.url, { opacity: 0, zIndex: 5, maxNativeZoom: source.maxNativeZoom, maxZoom: 9, attribution }).addTo(map),
    )
    return () => {
      layersRef.current.forEach((layer) => layer.remove())
      layersRef.current = []
    }
  }, [source])

  useEffect(() => {
    layersRef.current.forEach((layer, i) => layer.setOpacity(i === index ? (mode === 'radar' ? 0.75 : 0.7) : 0))
  }, [index, source])

  useEffect(() => {
    if (!playing || !source || source.frames.length < 2) return
    const id = setInterval(() => setIndex((i) => (i + 1) % source.frames.length), 800)
    return () => clearInterval(id)
  }, [playing, source])

  const frame = source?.frames[index]

  return (
    <section className="radar" aria-label="Live rain map">
      <header className="radar-head">
        <div className="radar-modes" role="tablist" aria-label="Rain data source">
          <button role="tab" aria-selected={mode === 'radar'} className={mode === 'radar' ? 'on' : ''} onClick={() => setMode('radar')}>
            <Radar size={13} /> Radar
          </button>
          <button role="tab" aria-selected={mode === 'satellite'} className={mode === 'satellite' ? 'on' : ''} onClick={() => setMode('satellite')}>
            <Satellite size={13} /> Satellite · NASA
          </button>
        </div>
        <small>{error ?? (frame ? `${new Date(frame.time * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} · ${age(frame.time)}` : 'loading…')}</small>
        <button className="icon-btn" onClick={() => setPlaying(!playing)} aria-label={playing ? 'Pause loop' : 'Play loop'}>
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
      </header>
      <div ref={holder} className="radar-map" />
      {source && source.frames.length > 1 && (
        <input
          className="radar-scrub"
          type="range"
          min={0}
          max={source.frames.length - 1}
          value={index}
          onChange={(e) => {
            setPlaying(false)
            setIndex(Number(e.target.value))
          }}
          aria-label="Map time"
        />
      )}
      <div className="radar-foot">
        <span className={`rain-legend ${mode}`}>
          <i />
          <em>light</em>
          <em>heavy</em>
        </span>
        <p className="radar-note">{NOTES[mode]}</p>
      </div>
    </section>
  )
}
