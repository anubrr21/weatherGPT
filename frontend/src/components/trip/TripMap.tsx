import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Radar } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { clock, duration, levelColor, type TripResult } from '../../lib/trip'

const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const RAINVIEWER = 'https://api.rainviewer.com/public/weather-maps.json'

interface Props {
  trip: TripResult
  selected: number
  onSelect: (index: number) => void
  lite: boolean
}

function nearestIndex(geometry: [number, number][], lat: number, lon: number, from: number) {
  let best = from
  let bestD = Infinity
  for (let i = from; i < geometry.length; i++) {
    const d = (geometry[i][0] - lat) ** 2 + (geometry[i][1] - lon) ** 2
    if (d < bestD) {
      bestD = d
      best = i
    }
  }
  return best
}

function escape(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
}

export default function TripMap({ trip, selected, onSelect, lite }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const radarRef = useRef<L.TileLayer | null>(null)
  const [radar, setRadar] = useState(false)
  const [radarNote, setRadarNote] = useState<string | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 3, maxZoom: 13 })
    L.tileLayer(BASEMAP, { maxZoom: 13, className: 'radar-basemap', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const flight = trip.mode === 'flight'
    trip.routes.forEach((route, index) => {
      if (index === selected) return
      L.polyline(route.geometry, { color: '#9aa6b8', weight: 4, opacity: 0.55, dashArray: '6 8' })
        .on('click', () => onSelect(index))
        .bindTooltip(`${route.summary} · ${route.risk.label} risk · tap to compare`, { sticky: true })
        .addTo(layer)
    })
    const route = trip.routes[selected]
    if (!route) return
    L.polyline(route.geometry, { color: '#0b0f16', weight: 9, opacity: 0.75 }).addTo(layer)
    let cursor = 0
    route.points.forEach((point, k) => {
      const next = route.points[k + 1]
      if (!next) return
      const a = nearestIndex(route.geometry, point.lat, point.lon, cursor)
      const b = nearestIndex(route.geometry, next.lat, next.lon, a)
      cursor = a
      const slice = route.geometry.slice(a, Math.max(a + 2, b + 1))
      L.polyline(slice, { color: levelColor(Math.max(point.level, next.level)), weight: 5, opacity: 0.95, dashArray: flight ? '2 9' : undefined, lineCap: 'round' }).addTo(layer)
    })
    route.points.forEach((point, k) => {
      if (k === 0 || k === route.points.length - 1) return
      const w = point.weather
      const lines = [
        `<b>${escape(point.place ?? `${point.km} km`)}</b> · ${clock(point.eta)}`,
        w ? `${escape(w.label)}, ${w.temp !== null ? Math.round(w.temp) : '–'}°C${w.rain_mmh ? `, rain ${w.rain_mmh.toFixed(1)} mm/h` : ''}` : 'No forecast for this time',
        ...point.hazards.map((h) => `⚠ ${escape(h.detail)}`),
      ]
      L.circleMarker([point.lat, point.lon], { radius: point.level >= 1 ? 7 : 5, color: '#0b0f16', weight: 2, fillColor: levelColor(point.level), fillOpacity: 1 })
        .bindTooltip(lines.join('<br>'), { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    })
    const ends = [
      { at: route.geometry[0], label: `Start · ${trip.origin.name} · ${clock(route.depart)}` },
      { at: route.geometry[route.geometry.length - 1], label: `Arrive · ${trip.destination.name} · ${clock(route.arrive)}` },
    ]
    ends.forEach((end, k) =>
      L.circleMarker(end.at, { radius: 9, color: '#fff', weight: 3, fillColor: k ? '#ff6a3d' : '#3ddc97', fillOpacity: 1 })
        .bindTooltip(escape(end.label), { direction: 'top', permanent: false })
        .addTo(layer),
    )
    ;(route.vias ?? []).forEach((via, k) =>
      L.marker([via.lat, via.lon], {
        icon: L.divIcon({ className: 'trip-via-pin', html: `<b>${k + 1}</b>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
        zIndexOffset: 500,
      })
        .bindTooltip(`<b>Stop ${k + 1}</b> · ${escape(via.name)}<br>${clock(via.eta)} · km ${Math.round(via.km)}`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer),
    )
    const dots: Record<string, string> = { services: '#ffb45c', rest_area: '#ffb45c', fuel: '#6fe3ff', restaurant: '#ff8fb1', fast_food: '#ff8fb1', cafe: '#ff8fb1', hotel: '#c4b3ff', motel: '#c4b3ff', guest_house: '#c4b3ff' }
    const along = route.stops_along?.places ?? []
    along.forEach((place) =>
      L.circleMarker([place.lat, place.lon], { radius: 3.5, color: '#0b0f16', weight: 1, fillColor: dots[place.kind] ?? '#ffffff', fillOpacity: 0.95 })
        .bindTooltip(`${escape(place.name)}<br>after ${duration(place.after_min)} · km ${Math.round(place.km)}${place.google ? `<br>★ ${place.google.rating.toFixed(1)} on Google` : ''}`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer),
    )
    const stops = route.rest_stops ?? []
    stops.forEach((stop, k) => {
      stop.options.slice(0, 3).forEach((option) =>
        L.circleMarker([option.lat, option.lon], { radius: 4, color: '#0b0f16', weight: 1, fillColor: '#6fe3ff', fillOpacity: 0.95 })
          .bindTooltip(`${escape(option.name)}<br>${option.detour_km} km off route`, { direction: 'top', className: 'trip-tip' })
          .addTo(layer),
      )
      const title = stop.reason === 'overnight' ? 'Overnight stay' : `Break ${k + 1}`
      const lines = [`<b>${title}</b> · ${escape(stop.near ?? `km ${Math.round(stop.km)}`)}`, ...stop.options.slice(0, 3).map((o) => `• ${escape(o.name)}`)]
      L.circleMarker([stop.lat, stop.lon], { radius: 9, color: '#ffffff', weight: 3, fillColor: stop.reason === 'overnight' ? '#9b7bff' : '#ff9933', fillOpacity: 1 })
        .bindTooltip(lines.join('<br>'), { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    })
    const extras = [route.extra.from_airport, route.extra.to_airport, route.extra.from_station, route.extra.to_station, ...(route.extra.via_airports ?? []), ...(route.extra.via_stations ?? [])].filter(Boolean)
    extras.forEach((spot) => {
      if (!spot) return
      L.circleMarker([spot.lat, spot.lon], { radius: 6, color: '#6fb7ff', weight: 2, fillColor: '#0b0f16', fillOpacity: 1 }).bindTooltip(escape(spot.name)).addTo(layer)
    })
    map.fitBounds(L.latLngBounds(route.geometry), { padding: [36, 36] })
  }, [trip, selected])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    radarRef.current?.remove()
    radarRef.current = null
    if (!radar) return
    let cancelled = false
    fetch(RAINVIEWER)
      .then((r) => r.json())
      .then((data: { host: string; radar: { past: { path: string; time: number }[]; nowcast?: { path: string; time: number }[] } }) => {
        if (cancelled) return
        const frames = [...data.radar.past, ...(data.radar.nowcast ?? [])]
        const latest = data.radar.past[data.radar.past.length - 1] ?? frames[frames.length - 1]
        radarRef.current = L.tileLayer(`${data.host}${latest.path}/256/{z}/{x}/{y}/4/1_1.png`, { opacity: 0.65, zIndex: 5, maxNativeZoom: 7, maxZoom: 13, attribution: 'Radar © RainViewer' }).addTo(map)
        setRadarNote(`Radar ${new Date(latest.time * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })} · coverage over India is partial`)
      })
      .catch(() => !cancelled && setRadarNote('Radar feed unavailable right now'))
    return () => {
      cancelled = true
    }
  }, [radar])

  return (
    <section className="trip-map">
      <div ref={holder} className="trip-map-canvas" />
      <div className="trip-map-legend">
        {['Low', 'Moderate', 'High', 'Severe'].map((label, i) => (
          <span key={label}>
            <i style={{ background: levelColor(i) }} /> {label}
          </span>
        ))}
      </div>
      <button className={`trip-radar ${radar ? 'on' : ''}`} onClick={() => setRadar(!radar)} title={lite ? 'Radar uses extra data' : 'Show live rain radar'}>
        <Radar size={14} /> {radar ? 'Radar on' : 'Live radar'}
      </button>
      {radar && radarNote && <p className="trip-radar-note">{radarNote}</p>}
    </section>
  )
}
