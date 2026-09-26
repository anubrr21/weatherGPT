import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Pause, Play, Radar } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Place } from '../lib/types'

interface Frame {
  time: number
  path: string
}

const FRAMES_URL = 'https://api.rainviewer.com/public/weather-maps.json'
const BASEMAP = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'

export default function RadarMap({ place }: { place: Place }) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.CircleMarker | null>(null)
  const layersRef = useRef<L.TileLayer[]>([])
  const [frames, setFrames] = useState<Frame[]>([])
  const [host, setHost] = useState('')
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, attributionControl: true, minZoom: 3, maxZoom: 9 }).setView([place.lat, place.lon], 6)
    L.tileLayer(BASEMAP, {
      subdomains: 'abcd',
      attribution: '© OpenStreetMap © CARTO · Radar © RainViewer',
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
      fetch(FRAMES_URL)
        .then((r) => r.json())
        .then((data: { host: string; radar: { past: Frame[]; nowcast?: Frame[] } }) => {
          if (cancelled) return
          const all = [...data.radar.past, ...(data.radar.nowcast ?? [])]
          setHost(data.host)
          setFrames(all)
          setIndex(all.length - 1)
          setError(null)
        })
        .catch(() => !cancelled && setError('Radar feed unavailable right now'))
    load()
    const id = setInterval(load, 10 * 60 * 1000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !host || !frames.length) return
    layersRef.current.forEach((layer) => layer.remove())
    layersRef.current = frames.map((frame) =>
      L.tileLayer(`${host}${frame.path}/256/{z}/{x}/{y}/4/1_1.png`, { opacity: 0, zIndex: 5, maxNativeZoom: 7, maxZoom: 9 }).addTo(map),
    )
    return () => layersRef.current.forEach((layer) => layer.remove())
  }, [host, frames])

  useEffect(() => {
    layersRef.current.forEach((layer, i) => layer.setOpacity(i === index ? 0.75 : 0))
  }, [index, frames])

  useEffect(() => {
    if (!playing || frames.length < 2) return
    const id = setInterval(() => setIndex((i) => (i + 1) % frames.length), 700)
    return () => clearInterval(id)
  }, [playing, frames.length])

  const frame = frames[index]
  const minutesAgo = frame ? Math.round((Date.now() / 1000 - frame.time) / 60) : null

  return (
    <section className="radar" aria-label="Live precipitation radar">
      <header className="radar-head">
        <span>
          <Radar size={14} /> Live radar
        </span>
        <small>{error ?? (frame ? `${new Date(frame.time * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} · ${minutesAgo! <= 5 ? 'latest' : `${minutesAgo} min ago`}` : 'loading…')}</small>
        <button className="icon-btn" onClick={() => setPlaying(!playing)} aria-label={playing ? 'Pause radar loop' : 'Play radar loop'}>
          {playing ? <Pause size={15} /> : <Play size={15} />}
        </button>
      </header>
      <div ref={holder} className="radar-map" />
      {frames.length > 1 && (
        <input
          className="radar-scrub"
          type="range"
          min={0}
          max={frames.length - 1}
          value={index}
          onChange={(e) => {
            setPlaying(false)
            setIndex(Number(e.target.value))
          }}
          aria-label="Radar time"
        />
      )}
    </section>
  )
}
