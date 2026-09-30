import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import { SCALES, colorAt, compass, sampler, type FieldData, type FieldKey, type MapWarning } from '../../lib/maps'
import { severityColor } from '../../lib/lightning'
import type { Place } from '../../lib/types'

const BASEMAP = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const BLOCK = 3
const PARTICLES = 1400

interface Props {
  data: FieldData | null
  field: FieldKey
  frame: number
  particles: boolean
  warnings: MapWarning[]
  showWarnings: boolean
  place: Place | null
}

interface Readout {
  x: number
  y: number
  lines: string[]
}

function escape(text: string) {
  return text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c)
}

const until = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) : '–'

export default function FieldMap({ data, field, frame, particles, warnings, showWarnings, place }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const rasterRef = useRef<HTMLCanvasElement | null>(null)
  const flowRef = useRef<HTMLCanvasElement | null>(null)
  const warnLayer = useRef<L.LayerGroup | null>(null)
  const placeLayer = useRef<L.LayerGroup | null>(null)
  const stateRef = useRef({ data, field, frame, particles })
  const redrawRef = useRef<() => void>(() => undefined)
  const [readout, setReadout] = useState<Readout | null>(null)

  stateRef.current = { data, field, frame, particles }

  useEffect(() => {
    if (!holder.current || mapRef.current) return
    const map = L.map(holder.current, { zoomControl: false, minZoom: 4, maxZoom: 9, maxBounds: [[-5, 55], [45, 110]] }).setView([22, 82], 5)
    L.tileLayer(BASEMAP, { maxZoom: 9, className: 'radar-basemap', attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · Open-Meteo' }).addTo(map)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    const fieldPane = map.createPane('fieldPane')
    fieldPane.style.zIndex = '350'
    fieldPane.style.pointerEvents = 'none'
    const flowPane = map.createPane('flowPane')
    flowPane.style.zIndex = '360'
    flowPane.style.pointerEvents = 'none'
    const raster = L.DomUtil.create('canvas', 'field-canvas', fieldPane)
    const flow = L.DomUtil.create('canvas', 'field-canvas', flowPane)
    rasterRef.current = raster
    flowRef.current = flow
    warnLayer.current = L.layerGroup().addTo(map)
    placeLayer.current = L.layerGroup().addTo(map)
    mapRef.current = map

    let origin = L.point(0, 0)
    let seeds: { lat: number; lon: number; age: number }[] = []
    let raf = 0
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const reset = () => {
      const size = map.getSize()
      origin = map.containerPointToLayerPoint([0, 0])
      for (const canvas of [raster, flow]) {
        canvas.width = size.x
        canvas.height = size.y
        canvas.style.width = `${size.x}px`
        canvas.style.height = `${size.y}px`
        L.DomUtil.setPosition(canvas, origin)
      }
      paint()
      seeds = []
      flow.getContext('2d')?.clearRect(0, 0, size.x, size.y)
    }

    const paint = () => {
      const { data: d, field: f, frame: fr } = stateRef.current
      const ctx = raster.getContext('2d')
      if (!ctx) return
      ctx.clearRect(0, 0, raster.width, raster.height)
      if (!d || raster.width < BLOCK || raster.height < BLOCK) return
      const sample = sampler(d)
      const key = f === 'wind' ? 'speed' : f
      const values = d.fields[key][Math.min(fr, d.times.length - 1)]
      const scale = SCALES[f]
      const w = Math.ceil(raster.width / BLOCK)
      const h = Math.ceil(raster.height / BLOCK)
      const small = new ImageData(w, h)
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          const ll = map.containerPointToLatLng([x * BLOCK + BLOCK / 2, y * BLOCK + BLOCK / 2])
          const v = sample(values, ll.lat, ll.lng)
          if (v === null) continue
          const [r, g, b, a] = colorAt(scale, v)
          const i = (y * w + x) * 4
          small.data[i] = r
          small.data[i + 1] = g
          small.data[i + 2] = b
          small.data[i + 3] = a
        }
      }
      const off = document.createElement('canvas')
      off.width = w
      off.height = h
      off.getContext('2d')?.putImageData(small, 0, 0)
      ctx.imageSmoothingEnabled = true
      ctx.drawImage(off, 0, 0, w * BLOCK, h * BLOCK)
    }

    const animate = () => {
      raf = requestAnimationFrame(animate)
      const { data: d, frame: fr, particles: on } = stateRef.current
      const ctx = flow.getContext('2d')
      if (!ctx) return
      if (!d || !on || reduced || document.visibilityState !== 'visible') {
        if (seeds.length) {
          ctx.clearRect(0, 0, flow.width, flow.height)
          seeds = []
        }
        return
      }
      const sample = sampler(d)
      const u = d.fields.u[Math.min(fr, d.times.length - 1)]
      const v = d.fields.v[Math.min(fr, d.times.length - 1)]
      const bounds = map.getBounds()
      const zoomFactor = 0.0018 * 2 ** (5 - map.getZoom())
      const spawn = () => ({ lat: bounds.getSouth() + Math.random() * (bounds.getNorth() - bounds.getSouth()), lon: bounds.getWest() + Math.random() * (bounds.getEast() - bounds.getWest()), age: Math.floor(Math.random() * 90) })
      while (seeds.length < PARTICLES) seeds.push(spawn())
      ctx.globalCompositeOperation = 'destination-in'
      ctx.fillStyle = 'rgba(0, 0, 0, 0.93)'
      ctx.fillRect(0, 0, flow.width, flow.height)
      ctx.globalCompositeOperation = 'source-over'
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.85)'
      ctx.lineWidth = 1.3
      ctx.beginPath()
      for (let k = 0; k < seeds.length; k++) {
        const p = seeds[k]
        const pu = sample(u, p.lat, p.lon)
        const pv = sample(v, p.lat, p.lon)
        if (pu === null || pv === null || p.age > 110) {
          seeds[k] = spawn()
          seeds[k].age = 0
          continue
        }
        const from = map.latLngToLayerPoint([p.lat, p.lon]).subtract(origin)
        p.lat += pv * zoomFactor
        p.lon += (pu * zoomFactor) / Math.cos((p.lat * Math.PI) / 180)
        p.age += 1
        const to = map.latLngToLayerPoint([p.lat, p.lon]).subtract(origin)
        ctx.moveTo(from.x, from.y)
        ctx.lineTo(to.x, to.y)
      }
      ctx.stroke()
    }

    redrawRef.current = paint
    map.on('moveend zoomend resize viewreset', reset)
    map.on('zoomstart', () => {
      raster.style.opacity = '0'
      flow.style.opacity = '0'
    })
    map.on('zoomend', () => {
      raster.style.opacity = ''
      flow.style.opacity = ''
    })
    map.on('mousemove', (e: L.LeafletMouseEvent) => {
      const d = stateRef.current.data
      if (!d) return
      const sample = sampler(d)
      const fr = Math.min(stateRef.current.frame, d.times.length - 1)
      const at = (k: keyof FieldData['fields']) => sample(d.fields[k][fr], e.latlng.lat, e.latlng.lng)
      const temp = at('temp')
      if (temp === null) {
        setReadout(null)
        return
      }
      const u = at('u') ?? 0
      const v = at('v') ?? 0
      setReadout({
        x: e.containerPoint.x,
        y: e.containerPoint.y,
        lines: [
          `${temp.toFixed(1)} °C`,
          `Wind ${Math.round(at('speed') ?? 0)} km/h from ${compass(u, v)}`,
          `Rain ${(at('rain') ?? 0).toFixed(1)} mm / 3 h`,
          `Cloud ${Math.round(at('cloud') ?? 0)}% · ${Math.round(at('pressure') ?? 0)} hPa`,
        ],
      })
    })
    map.on('mouseout', () => setReadout(null))
    const observer = new ResizeObserver(() => {
      map.invalidateSize()
      reset()
    })
    observer.observe(holder.current)
    setTimeout(reset, 0)
    animate()
    return () => {
      cancelAnimationFrame(raf)
      observer.disconnect()
      map.remove()
      mapRef.current = null
    }
  }, [])

  useEffect(() => {
    redrawRef.current()
  }, [data, field, frame])

  useEffect(() => {
    const layer = warnLayer.current
    if (!layer) return
    layer.clearLayers()
    if (!showWarnings) return
    warnings.forEach((w) =>
      w.rings.forEach((ring) =>
        L.polygon(
          ring.map(([lon, lat]) => [lat, lon] as [number, number]),
          { color: severityColor(w.severity), weight: 1.2, opacity: 0.9, fillColor: severityColor(w.severity), fillOpacity: 0.28 },
        )
          .bindTooltip(`<b>${escape(w.event)}</b> · ${escape(w.severity ?? '')}<br>${escape(w.areas.join(', ').slice(0, 140))}<br>until ${until(w.expires)} · ${escape((w.issuer ?? '').replace(/^.*\(/, '').replace(/\)$/, ''))}`, { sticky: true, className: 'trip-tip' })
          .addTo(layer),
      ),
    )
  }, [warnings, showWarnings])

  useEffect(() => {
    const layer = placeLayer.current
    if (!layer) return
    layer.clearLayers()
    if (place) L.circleMarker([place.lat, place.lon], { radius: 6, color: '#ffffff', weight: 2.5, fillColor: '#ff9933', fillOpacity: 1 }).bindTooltip(escape(place.name)).addTo(layer)
  }, [place?.lat, place?.lon, place?.name])

  const scale = SCALES[field]
  const gradient = scale.stops.map(([value, c]) => {
    const low = scale.stops[0][0]
    const high = scale.stops[scale.stops.length - 1][0]
    return `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0.35, c[3] / 255)}) ${((value - low) / (high - low)) * 100}%`
  })

  return (
    <div className="trip-map field-map">
      <div ref={holder} className="field-map-canvas" />
      {readout && (
        <div className="field-readout" style={{ left: Math.min(readout.x + 14, (holder.current?.clientWidth ?? 400) - 170), top: Math.max(8, readout.y - 70) }}>
          {readout.lines.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      )}
      <div className="field-legend">
        <b>
          {scale.label} ({scale.unit})
        </b>
        <i style={{ background: `linear-gradient(90deg, ${gradient.join(', ')})` }} />
        <span>
          {scale.ticks.map((t) => (
            <small key={t} style={{ left: `${((t - scale.stops[0][0]) / (scale.stops[scale.stops.length - 1][0] - scale.stops[0][0])) * 100}%` }}>
              {t}
            </small>
          ))}
        </span>
      </div>
    </div>
  )
}
