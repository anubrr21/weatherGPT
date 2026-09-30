import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { RISK_COLORS, RISK_LABELS, ageColor, severityColor, type LightningLive, type LightningRisk } from '../../lib/lightning'
import type { Place } from '../../lib/types'

const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

interface Props {
  live: LightningLive | null
  risk: LightningRisk | null
  place: Place
  focus: string | null
  showRisk: boolean
}

function escape(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
}

const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : '–'

export default function LightningMap({ live, risk, place, focus, showRisk }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const baseRef = useRef<L.LayerGroup | null>(null)
  const strikeRef = useRef<L.LayerGroup | null>(null)
  const fittedFor = useRef<string | null>(null)

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 4, maxZoom: 12, preferCanvas: true }).setView([place.lat, place.lon], 7)
    L.tileLayer(BASEMAP, { maxZoom: 12, className: 'radar-basemap', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    baseRef.current = L.layerGroup().addTo(map)
    strikeRef.current = L.layerGroup().addTo(map)
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = baseRef.current
    if (!map || !layer) return
    layer.clearLayers()
    if (showRisk && risk) {
      const half = risk.grid.step / 2
      risk.grid.cells
        .filter((c) => c.score > 0)
        .forEach((c) =>
          L.rectangle(
            [
              [c.lat - half, c.lon - half],
              [c.lat + half, c.lon + half],
            ],
            { stroke: false, fillColor: RISK_COLORS[c.score], fillOpacity: 0.16 + c.score * 0.07 },
          )
            .bindTooltip(`${RISK_LABELS[c.score]} thunderstorms in the next ${risk.grid.hours} h${c.time ? `, from ${clock(c.time)}` : ''}<br>CAPE up to ${c.cape} J/kg`, { sticky: true, className: 'trip-tip' })
            .addTo(layer),
        )
    }
    live?.official.forEach((area) => {
      const focused = area.id === focus
      area.rings.forEach((ring) =>
        L.polygon(
          ring.map(([lon, lat]) => [lat, lon] as [number, number]),
          { color: severityColor(area.severity), weight: focused ? 3 : 1.5, opacity: 0.95, fillColor: severityColor(area.severity), fillOpacity: focused ? 0.3 : 0.16 },
        )
          .bindTooltip(`<b>${escape(area.event ?? 'Warning')}</b> · ${escape(area.severity ?? '')}<br>${escape(area.areas.join(', '))}<br>until ${clock(area.expires)} · ${escape((area.issuer ?? '').replace(/^.*\(/, '').replace(/\)$/, ''))}`, { sticky: true, className: 'trip-tip' })
          .addTo(layer),
      )
    })
    ;[10, 20, 30].forEach((r) =>
      L.circle([place.lat, place.lon], { radius: r * 1000, color: '#ffffff', weight: 1, opacity: 0.35, dashArray: '3 6', fill: false, interactive: false }).addTo(layer),
    )
    L.circleMarker([place.lat, place.lon], { radius: 7, color: '#ffffff', weight: 3, fillColor: '#ff9933', fillOpacity: 1 }).bindTooltip(escape(place.name)).addTo(layer)
    if (live?.motion) {
      const m = live.motion
      L.circleMarker([m.centre.lat, m.centre.lon], { radius: 10, color: '#ffe066', weight: 2, fill: false })
        .bindTooltip(`Storm cell moving ${m.heading} at ${m.speed_kmh} km/h${m.eta_min ? ` · reaches ${escape(place.name)} in about ${m.eta_min} min` : ''}`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    }
    const target = focus ? live?.official.find((a) => a.id === focus) : null
    if (target && target.rings.length) {
      map.fitBounds(L.latLngBounds(target.rings.flat().map(([lon, lat]) => [lat, lon] as [number, number])), { padding: [30, 30], maxZoom: 9 })
      fittedFor.current = `area:${focus}`
    } else if (fittedFor.current !== `place:${place.lat},${place.lon}`) {
      map.setView([place.lat, place.lon], 7)
      fittedFor.current = `place:${place.lat},${place.lon}`
    }
  }, [live?.official, live?.motion, risk, showRisk, place.lat, place.lon, place.name, focus])

  useEffect(() => {
    const layer = strikeRef.current
    if (!layer) return
    layer.clearLayers()
    if (!live) return
    const now = Date.now() / 1000
    live.strikes.forEach((s) => {
      const age = (now - s.t) / 60
      L.circleMarker([s.lat, s.lon], { radius: age <= 5 ? 5 : 3.5, color: '#0b0f16', weight: 1, fillColor: ageColor(age), fillOpacity: 0.95, className: age <= 2 ? 'strike-new' : '' })
        .bindTooltip(`${Math.round(age)} min ago · ${s.km} km away · ${s.stations} detectors`, { direction: 'top', className: 'trip-tip' })
        .addTo(layer)
    })
  }, [live?.strikes])

  return (
    <div className="trip-map lightning-map">
      <div ref={holder} className="trip-map-canvas" />
      <div className="trip-map-legend">
        <span>
          <i style={{ background: '#ffffff' }} /> 0–5 min
        </span>
        <span>
          <i style={{ background: '#ffe066' }} /> 15
        </span>
        <span>
          <i style={{ background: '#ff9f43' }} /> 30
        </span>
        <span>
          <i style={{ background: '#ff4d6d' }} /> 60
        </span>
        <span>
          <i className="poly" /> official
        </span>
      </div>
    </div>
  )
}
