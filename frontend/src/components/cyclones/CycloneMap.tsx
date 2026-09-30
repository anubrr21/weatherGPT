import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { gradeColor, ist, stormLabel, type LiveStorm, type Shelter } from '../../lib/cyclones'
import type { Place } from '../../lib/types'

const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const RADII_COLORS: Record<number, string> = { 60: '#ffd166', 90: '#ff8c42', 120: '#ff3d6e' }

export interface HistoryTrack {
  sid: string
  label: string
  points: [number, number, number | null][]
  highlight: boolean
}

interface Props {
  storms: LiveStorm[]
  focus: string | null
  history: HistoryTrack[]
  place: Place | null
  shelters: Shelter[]
  onPickStorm: (id: string) => void
}

function escape(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
}

const toLatLngs = (ring: number[][]) => ring.map(([lon, lat]) => [lat, lon] as [number, number])

function polygons(geometry: LiveStorm['shapes']['cone']): [number, number][][] {
  if (!geometry) return []
  if (geometry.type === 'Polygon') return [toLatLngs(geometry.coordinates[0])]
  return geometry.coordinates.map((poly) => toLatLngs(poly[0]))
}

const levelOfKt = (kt: number | null) => (kt === null ? 0 : kt >= 120 ? 7 : kt >= 90 ? 6 : kt >= 64 ? 5 : kt >= 48 ? 4 : kt >= 34 ? 3 : kt >= 28 ? 2 : kt >= 17 ? 1 : 0)

export default function CycloneMap({ storms, focus, history, place, shelters, onPickStorm }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 3, maxZoom: 12, worldCopyJump: true }).setView([16, 84], 4)
    L.tileLayer(BASEMAP, { maxZoom: 12, className: 'radar-basemap', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map)
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
    const bounds: [number, number][] = []

    history.forEach((track) => {
      const line = track.points.map((p) => [p[0], p[1]] as [number, number])
      if (track.highlight) bounds.push(...line)
      track.points.slice(0, -1).forEach((p, k) => {
        const next = track.points[k + 1]
        L.polyline([[p[0], p[1]], [next[0], next[1]]], { color: gradeColor(levelOfKt(Math.max(p[2] ?? 0, next[2] ?? 0))), weight: track.highlight ? 4 : 2, opacity: track.highlight ? 0.95 : 0.45 })
          .bindTooltip(escape(track.label), { sticky: true, className: 'trip-tip' })
          .addTo(layer)
      })
    })

    storms.forEach((storm) => {
      const focused = storm.id === focus
      const shapes = storm.shapes
      polygons(shapes.cone).forEach((ring) => {
        L.polygon(ring, { color: '#ffffff', weight: 1, opacity: focused ? 0.6 : 0.25, dashArray: '4 6', fillColor: '#ffffff', fillOpacity: focused ? 0.08 : 0.03 }).addTo(layer)
        if (focused) bounds.push(...ring)
      })
      if (focused) {
        shapes.radii.forEach((radius) =>
          polygons(radius.geometry).forEach((ring) =>
            L.polygon(ring, { color: RADII_COLORS[radius.kmh], weight: 1, opacity: 0.55, fillColor: RADII_COLORS[radius.kmh], fillOpacity: 0.07 })
              .bindTooltip(`${radius.kmh}+ km/h winds · ${ist(radius.time)}`, { sticky: true, className: 'trip-tip' })
              .addTo(layer),
          ),
        )
      }
      storm.track.slice(0, -1).forEach((fix, k) => {
        const next = storm.track[k + 1]
        L.polyline([[fix.lat, fix.lon], [next.lat, next.lon]], {
          color: gradeColor(fix.grade?.level),
          weight: focused ? 5 : 3,
          opacity: focused ? 1 : 0.6,
          dashArray: next.forecast ? '8 8' : undefined,
          lineCap: 'round',
        })
          .on('click', () => onPickStorm(storm.id))
          .addTo(layer)
      })
      storm.track.forEach((fix) => {
        bounds.push([fix.lat, fix.lon])
        L.circleMarker([fix.lat, fix.lon], { radius: focused ? 5 : 3, color: '#0b0f16', weight: 1.5, fillColor: gradeColor(fix.grade?.level), fillOpacity: fix.forecast ? 0.55 : 1 })
          .bindTooltip(
            `<b>${escape(stormLabel(storm.name, storm.start, storm.peak))}</b>${fix.forecast ? ' · forecast' : ''}<br>${ist(fix.time)}<br>${fix.grade ? `${fix.grade.label} · ${fix.grade.kmh} km/h` : 'Intensity not given'}${fix.pressure ? ` · ${fix.pressure} hPa` : ''}`,
            { direction: 'top', className: 'trip-tip' },
          )
          .on('click', () => onPickStorm(storm.id))
          .addTo(layer)
      })
      if (storm.current) {
        L.marker([storm.now.lat, storm.now.lon], {
          icon: L.divIcon({ className: 'cyclone-eye', html: '<i></i>', iconSize: [34, 34], iconAnchor: [17, 17] }),
          zIndexOffset: 800,
        })
          .bindTooltip(`<b>${escape(stormLabel(storm.name, storm.start, storm.now.grade))}</b><br>Now: ${storm.now.grade?.label ?? ''} · ${storm.now.grade?.kmh ?? '–'} km/h`, { direction: 'top', className: 'trip-tip' })
          .addTo(layer)
      }
    })

    shelters.forEach((shelter) =>
      L.circleMarker([shelter.lat, shelter.lon], { radius: shelter.kind === 'public' ? 3.5 : 5.5, color: '#0b0f16', weight: 1, fillColor: shelter.kind === 'public' ? '#9fd1ff' : '#5fd39a', fillOpacity: 0.95 })
        .bindTooltip(`${escape(shelter.name ?? shelter.label)}<br>${escape(shelter.label)} · ${shelter.km} km`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer),
    )

    if (place) {
      L.circleMarker([place.lat, place.lon], { radius: 8, color: '#ffffff', weight: 3, fillColor: '#ff9933', fillOpacity: 1 })
        .bindTooltip(escape(place.name), { direction: 'top', permanent: false })
        .addTo(layer)
      bounds.push([place.lat, place.lon])
    }

    if (bounds.length > 1) map.fitBounds(L.latLngBounds(bounds), { padding: [30, 30], maxZoom: 7 })
    else if (place) map.setView([place.lat, place.lon], 6)
  }, [storms, focus, history, place, shelters, onPickStorm])

  return (
    <div className="trip-map cyclone-map">
      <div ref={holder} className="trip-map-canvas" />
      <div className="trip-map-legend cyclone-legend">
        {['D', 'DD', 'CS', 'SCS', 'VSCS', 'ESCS', 'SuCS'].map((code, k) => (
          <span key={code}>
            <i style={{ background: gradeColor(k + 1) }} />
            {code}
          </span>
        ))}
        <span>
          <i className="dash" /> forecast
        </span>
      </div>
    </div>
  )
}
