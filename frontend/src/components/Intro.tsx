import { useEffect, useRef, useState } from 'react'
import { LogoMark, Wordmark } from './Logo'
import { TOWN_POINTS } from '../lib/introTowns'
import { recall } from '../lib/offline'
import type { Forecast, Place, Sky } from '../lib/types'
import './intro.css'

const TAU = Math.PI * 2
const BACKDROP = '7, 11, 22'
const MAP_IN = 0.9
const MAP_HOLD = 2.0
const MAP_OUT = 2.9
const SWIRL_IN = 3.3
const EMBLEM_IN = 4.0
const EMBLEM_SET = 4.6
const STRIKE = 4.9
const REVEAL = 5.8
const END = 6.5
const CALM_END = 1100
const FRESH_MS = 6 * 3600 * 1000
const LON0 = 68
const LAT0 = 6.5
const LON_SPAN = 29.5
const LAT_SPAN = 30.7
const SQUEEZE = 0.927
const WIND_SHARE = 0.24

type Phase = 'forming' | 'struck' | 'leaving'

interface Scene {
  palette: string[]
  tint: string
  angle: number
  speed: number
  rain: number
  snow: boolean
  stars: boolean
  place: Place | null
  temperature: number | null
  detail: string
  caption: string
}

const PALETTES: Record<string, string[]> = {
  day: ['#ffd27a', '#ffb35c', '#ff8a4c', '#fff3c4'],
  night: ['#8fd3ff', '#b9a5ff', '#5f8bff', '#e6f4ff'],
  cloud: ['#c9d6ea', '#8fd3ff', '#9fb4d8', '#f4f6fb'],
  rain: ['#5ec8ff', '#8fd3ff', '#3f8cff', '#d7efff'],
  snow: ['#ffffff', '#d7efff', '#b8d8ff', '#8fd3ff'],
  thunder: ['#c7a6ff', '#8fd3ff', '#7a6bff', '#fff3c4'],
}

const TINTS: Record<string, string> = {
  day: '255, 150, 70',
  night: '90, 110, 255',
  cloud: '130, 160, 210',
  rain: '50, 130, 255',
  snow: '170, 210, 255',
  thunder: '140, 90, 255',
}

const RAIN: Partial<Record<Sky, number>> = { drizzle: 0.35, rain: 0.7, heavy_rain: 1, thunder: 0.8, snow: 0.6 }

function moodFor(sky: Sky, day: boolean) {
  if (sky === 'thunder') return 'thunder'
  if (sky === 'snow') return 'snow'
  if (sky === 'drizzle' || sky === 'rain' || sky === 'heavy_rain') return 'rain'
  if (sky === 'overcast' || sky === 'fog') return 'cloud'
  return day ? 'day' : 'night'
}

function readScene(): Scene {
  const hour = new Date().getHours()
  const daylight = hour >= 6 && hour < 18
  const mood = daylight ? 'day' : 'night'
  const fallback: Scene = {
    palette: PALETTES[mood],
    tint: TINTS[mood],
    angle: -0.35,
    speed: 1,
    rain: 0,
    snow: false,
    stars: !daylight,
    place: null,
    temperature: null,
    detail: '',
    caption: 'Weather for India, in your words',
  }
  try {
    const place = (JSON.parse(localStorage.getItem('weathergpt:v1') ?? '{}') as { place?: Place }).place
    if (!place) return fallback
    const hit = recall<Forecast>('forecast', place.lat, place.lon)
    const now = hit?.data?.current
    if (!hit || !now) return { ...fallback, place, caption: place.name }
    const sky = now.condition.sky
    const day = now.is_day === 1
    const live = moodFor(sky, day)
    const bearing = ((now.wind_direction_10m + 180) * Math.PI) / 180
    const fresh = Date.now() - hit.savedAt < FRESH_MS
    return {
      palette: PALETTES[live],
      tint: TINTS[live],
      angle: Math.atan2(-Math.cos(bearing), Math.sin(bearing)),
      speed: Math.min(1.9, Math.max(0.75, 0.7 + now.wind_speed_10m / 40)),
      rain: RAIN[sky] ?? 0,
      snow: sky === 'snow',
      stars: !day && (sky === 'clear' || sky === 'partly'),
      place,
      temperature: fresh ? Math.round(now.temperature_2m) : null,
      detail: fresh ? `${now.condition.label} · wind ${Math.round(now.wind_speed_10m)} km/h ${now.wind_compass}` : '',
      caption: fresh ? now.condition.label : '',
    }
  } catch {
    return fallback
  }
}

const smooth = (from: number, to: number, value: number) => {
  const x = Math.min(1, Math.max(0, (value - from) / (to - from)))
  return x * x * (3 - 2 * x)
}

function emblemPoint(): [number, number] {
  const pick = Math.random()
  if (pick < 0.3) {
    const a = Math.random() * TAU
    return [44 * Math.cos(a), 44 * Math.sin(a)]
  }
  if (pick < 0.4) {
    const a = (Math.floor(Math.random() * 54) / 54) * TAU
    return [40 * Math.cos(a), 40 * Math.sin(a)]
  }
  if (pick < 0.95) {
    const main = pick < 0.76
    const reach = main ? 34 : 27
    const girth = main ? 5 : 3
    const d = reach * Math.random()
    const half = d < girth ? d : (girth * (reach - d)) / (reach - girth)
    const side = Math.random() < 0.55 ? (Math.random() < 0.5 ? -half : half) : (Math.random() * 2 - 1) * half
    const turn = Math.floor(Math.random() * 4) * (Math.PI / 2) + (main ? 0 : Math.PI / 4)
    const cos = Math.cos(turn)
    const sin = Math.sin(turn)
    return [side * cos + d * sin, side * sin - d * cos]
  }
  const a = Math.random() * TAU
  const r = 7 * Math.sqrt(Math.random())
  return [r * Math.cos(a), r * Math.sin(a)]
}

function jagged(x1: number, y1: number, x2: number, y2: number, spread: number, rounds: number) {
  let points: [number, number][] = [
    [x1, y1],
    [x2, y2],
  ]
  let reach = spread
  for (let round = 0; round < rounds; round += 1) {
    const next: [number, number][] = [points[0]]
    for (let i = 1; i < points.length; i += 1) {
      const [ax, ay] = points[i - 1]
      const [bx, by] = points[i]
      const length = Math.hypot(bx - ax, by - ay) || 1
      const shift = (Math.random() - 0.5) * reach
      next.push([(ax + bx) / 2 + (-(by - ay) / length) * shift, (ay + by) / 2 + ((bx - ax) / length) * shift], points[i])
    }
    points = next
    reach *= 0.55
  }
  return points
}

function makeBolt(cx: number, cy: number, height: number) {
  const startX = cx + (Math.random() - 0.5) * height * 0.35
  const trunk = jagged(startX, -30, cx, cy, height * 0.22, 6)
  const branches: [number, number][][] = []
  const count = 3 + Math.floor(Math.random() * 3)
  for (let i = 0; i < count; i += 1) {
    const [bx, by] = trunk[Math.floor(trunk.length * (0.15 + Math.random() * 0.6))]
    const lean = (Math.random() < 0.5 ? -1 : 1) * (0.5 + Math.random() * 0.7)
    const length = height * (0.12 + Math.random() * 0.2)
    branches.push(jagged(bx, by, bx + Math.sin(lean) * length, by + Math.cos(lean) * length, length * 0.3, 4))
  }
  return { trunk, branches }
}

function trace(ctx: CanvasRenderingContext2D, points: [number, number][]) {
  ctx.beginPath()
  ctx.moveTo(points[0][0], points[0][1])
  for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i][0], points[i][1])
  ctx.stroke()
}

export default function Intro() {
  const [scene] = useState(readScene)
  const [phase, setPhase] = useState<Phase>('forming')
  const [gone, setGone] = useState(false)
  const [size] = useState(() => Math.min(240, Math.max(150, Math.min(window.innerWidth, window.innerHeight) * 0.34)))
  const root = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const flash = useRef<HTMLDivElement>(null)
  const degrees = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const host = root.current
    const board = canvas.current
    const glass = overlay.current
    const ctx = board?.getContext('2d')
    const hud = glass?.getContext('2d')
    if (!host || !board || !glass || !ctx || !hud) {
      setGone(true)
      return
    }
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || document.hidden) {
      setPhase('struck')
      if (degrees.current && scene.temperature !== null) degrees.current.textContent = `${scene.temperature}°`
      const leave = window.setTimeout(() => setPhase('leaving'), CALM_END - 350)
      const end = window.setTimeout(() => setGone(true), CALM_END)
      host.classList.add('calm')
      return () => {
        window.clearTimeout(leave)
        window.clearTimeout(end)
      }
    }

    const width = window.innerWidth
    const height = window.innerHeight
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    for (const layer of [board, glass]) {
      layer.width = Math.round(width * dpr)
      layer.height = Math.round(height * dpr)
    }
    ctx.scale(dpr, dpr)
    hud.scale(dpr, dpr)
    ctx.lineCap = 'round'
    hud.lineCap = 'round'
    ctx.fillStyle = `rgb(${BACKDROP})`
    ctx.fillRect(0, 0, width, height)

    const cx = width / 2
    const cy = height * 0.42
    const mark = size
    const unit = mark / 136
    const scale = Math.max(0.8, Math.min(1.5, Math.min(width, height) / 620))
    const wave = 0.0042 / scale
    const far = Math.hypot(Math.max(cx, width - cx), Math.max(cy, height - cy)) + 80
    const eye = mark * 0.2

    const degree = Math.min((width * 0.9) / (LON_SPAN * SQUEEZE), (height * 0.68) / LAT_SPAN)
    const mapY = height * 0.47
    const projectX = (lon: number) => cx + ((lon - LON0) * SQUEEZE - (LON_SPAN * SQUEEZE) / 2) * degree
    const projectY = (lat: number) => mapY - (lat - LAT0 - LAT_SPAN / 2) * degree

    const available = TOWN_POINTS.length / 2
    const towns = Math.round(Math.min(available, Math.max(1700, (width * height) / 330)))
    const stride = available / towns
    const breezes = Math.round(towns * WIND_SHARE)
    const count = towns + breezes

    const x = new Float32Array(count)
    const y = new Float32Array(count)
    const vx = new Float32Array(count)
    const vy = new Float32Array(count)
    const mx = new Float32Array(count)
    const my = new Float32Array(count)
    const tx = new Float32Array(count)
    const ty = new Float32Array(count)
    const seed = new Float32Array(count)
    for (let i = 0; i < count; i += 1) {
      x[i] = Math.random() * width
      y[i] = Math.random() * height
      seed[i] = Math.random()
      const [ex, ey] = emblemPoint()
      tx[i] = cx + ex * unit
      ty[i] = cy + ey * unit
      if (i < towns) {
        const at = Math.floor(i * stride) * 2
        mx[i] = projectX(LON0 + TOWN_POINTS[at] / 50)
        my[i] = projectY(LAT0 + TOWN_POINTS[at + 1] / 50)
      }
    }

    const drops = Math.round(scene.rain * 150)
    const dropX = new Float32Array(drops)
    const dropY = new Float32Array(drops)
    const dropV = new Float32Array(drops)
    for (let i = 0; i < drops; i += 1) {
      dropX[i] = Math.random() * width * 1.2
      dropY[i] = Math.random() * height
      dropV[i] = (scene.snow ? 2.2 : 15) * (0.7 + Math.random() * 0.6)
    }
    const stars = scene.stars ? Array.from({ length: 110 }, () => [Math.random() * width, Math.random() * height, Math.random() * TAU, 0.5 + Math.random()]) : []

    const home = scene.place
    const homeInside = home !== null && home.lon >= LON0 && home.lon <= LON0 + LON_SPAN && home.lat >= LAT0 && home.lat <= LAT0 + LAT_SPAN
    const beaconX = homeInside ? projectX(home.lon) : projectX(79)
    const beaconY = homeInside ? projectY(home.lat) : projectY(22.5)
    const range = LAT_SPAN * degree * 0.36
    const position = homeInside ? `${Math.abs(home.lat).toFixed(2)}°N  ${Math.abs(home.lon).toFixed(2)}°E` : ''
    const reading = scene.temperature !== null ? `${scene.temperature}° · ${scene.detail}` : ''

    const bolts = [makeBolt(cx, cy, height), makeBolt(cx, cy, height)]
    let skew = 0
    let struck = false
    let leaving = false
    let finished = false
    let shown = ''
    let last = performance.now()
    const started = last
    let frame = 0

    const finish = () => {
      if (finished) return
      finished = true
      setGone(true)
    }
    const guard = window.setTimeout(finish, (END + 1.6) * 1000)
    const skip = () => {
      const t = (performance.now() - started) / 1000 + skew
      if (t < REVEAL) skew += REVEAL - t
    }
    host.addEventListener('pointerdown', skip)

    const drawMap = (t: number, show: number) => {
      hud.globalAlpha = show * 0.16
      hud.strokeStyle = '#9fd1ff'
      hud.fillStyle = '#9fd1ff'
      hud.lineWidth = 0.6
      hud.font = `500 9px 'JetBrains Mono', ui-monospace, monospace`
      hud.setLineDash([2, 6])
      hud.beginPath()
      for (let lon = 70; lon <= 95; lon += 5) {
        hud.moveTo(projectX(lon), projectY(LAT0 + LAT_SPAN))
        hud.lineTo(projectX(lon), projectY(LAT0))
      }
      for (let lat = 10; lat <= 35; lat += 5) {
        hud.moveTo(projectX(LON0), projectY(lat))
        hud.lineTo(projectX(LON0 + LON_SPAN), projectY(lat))
      }
      hud.stroke()
      hud.setLineDash([])
      hud.globalAlpha = show * 0.42
      hud.textAlign = 'center'
      for (let lon = 70; lon <= 95; lon += 5) hud.fillText(`${lon}°E`, projectX(lon), projectY(LAT0) + 12)
      hud.textAlign = 'left'
      for (let lat = 10; lat <= 35; lat += 5) hud.fillText(`${lat}°N`, Math.max(4, projectX(LON0) - 4), projectY(lat) - 3)

      const sweep = t * 3.4
      hud.lineWidth = 1
      for (let ring = 1; ring <= 3; ring += 1) {
        hud.globalAlpha = show * 0.2
        hud.beginPath()
        hud.arc(beaconX, beaconY, (range * ring) / 3, 0, TAU)
        hud.stroke()
      }
      for (let slice = 0; slice < 26; slice += 1) {
        const from = sweep - slice * 0.035
        hud.globalAlpha = show * 0.2 * (1 - slice / 26)
        hud.fillStyle = scene.palette[1]
        hud.beginPath()
        hud.moveTo(beaconX, beaconY)
        hud.arc(beaconX, beaconY, range, from - 0.04, from)
        hud.closePath()
        hud.fill()
      }
      hud.globalAlpha = show * 0.85
      hud.strokeStyle = scene.palette[3]
      hud.lineWidth = 1.2
      hud.beginPath()
      hud.moveTo(beaconX, beaconY)
      hud.lineTo(beaconX + Math.cos(sweep) * range, beaconY + Math.sin(sweep) * range)
      hud.stroke()

      for (let pulse = 0; pulse < 3; pulse += 1) {
        const life = (t * 0.9 + pulse / 3) % 1
        hud.globalAlpha = show * (1 - life) * 0.9
        hud.lineWidth = 1.6
        hud.strokeStyle = scene.palette[0]
        hud.beginPath()
        hud.arc(beaconX, beaconY, 4 + life * 46 * scale, 0, TAU)
        hud.stroke()
      }
      hud.globalAlpha = show
      hud.fillStyle = '#ffffff'
      hud.shadowColor = scene.palette[0]
      hud.shadowBlur = 14
      hud.beginPath()
      hud.arc(beaconX, beaconY, 3.6, 0, TAU)
      hud.fill()
      hud.shadowBlur = 0

      const arrow = 26 * scale
      hud.strokeStyle = scene.palette[3]
      hud.lineWidth = 1.6
      const tipX = beaconX + Math.cos(scene.angle) * arrow
      const tipY = beaconY + Math.sin(scene.angle) * arrow
      hud.beginPath()
      hud.moveTo(beaconX + Math.cos(scene.angle) * 9, beaconY + Math.sin(scene.angle) * 9)
      hud.lineTo(tipX, tipY)
      hud.moveTo(tipX, tipY)
      hud.lineTo(tipX - Math.cos(scene.angle - 0.5) * 7, tipY - Math.sin(scene.angle - 0.5) * 7)
      hud.moveTo(tipX, tipY)
      hud.lineTo(tipX - Math.cos(scene.angle + 0.5) * 7, tipY - Math.sin(scene.angle + 0.5) * 7)
      hud.stroke()

      if (homeInside) {
        const left = beaconX > width * 0.56
        const textX = beaconX + (left ? -16 : 16)
        hud.textAlign = left ? 'right' : 'left'
        hud.fillStyle = '#ffffff'
        hud.font = `600 ${Math.round(15 * Math.min(1.2, scale + 0.1))}px 'Inter Tight', system-ui, sans-serif`
        hud.fillText(home.name, textX, beaconY - 14)
        hud.font = `500 10px 'JetBrains Mono', ui-monospace, monospace`
        hud.globalAlpha = show * 0.75
        hud.fillStyle = '#cfe6ff'
        hud.fillText(position, textX, beaconY + 22)
        if (reading) hud.fillText(reading, textX, beaconY + 36)
      }
      hud.globalAlpha = 1
      hud.textAlign = 'left'
    }

    const draw = (stamp: number) => {
      const step = Math.min(2.5, (stamp - last) / 16.67)
      last = stamp
      const t = (stamp - started) / 1000 + skew
      const release = smooth(MAP_OUT, SWIRL_IN, t)
      const settle = smooth(EMBLEM_IN, EMBLEM_SET, t)
      const swirl = release * (1 - smooth(EMBLEM_IN + 0.2, EMBLEM_SET, t))
      const charted = smooth(MAP_IN + 0.5, MAP_HOLD + 0.3, t) * (1 - release)

      ctx.globalCompositeOperation = 'source-over'
      ctx.globalAlpha = 1
      ctx.fillStyle = `rgba(${BACKDROP}, ${0.1 + charted * 0.06 + settle * 0.16 - swirl * 0.035})`
      ctx.fillRect(0, 0, width, height)
      hud.clearRect(0, 0, width, height)

      if (stars.length) {
        const dim = 1 - smooth(STRIKE, REVEAL, t)
        ctx.fillStyle = '#e6f4ff'
        for (const [sx, sy, shift, radius] of stars) {
          ctx.globalAlpha = dim * (0.2 + 0.3 * Math.sin(t * 3 + shift) ** 2)
          ctx.fillRect(sx, sy, radius, radius)
        }
        ctx.globalAlpha = 1
      }

      if (drops && settle < 1) {
        const lean = Math.cos(scene.angle) * 0.35
        ctx.strokeStyle = scene.snow ? 'rgba(255, 255, 255, 0.55)' : 'rgba(170, 215, 255, 0.3)'
        ctx.lineWidth = scene.snow ? 1.6 : 1
        ctx.globalAlpha = 1 - settle
        ctx.beginPath()
        for (let i = 0; i < drops; i += 1) {
          const fall = dropV[i] * step
          dropY[i] += fall
          dropX[i] += fall * lean
          if (dropY[i] > height) {
            dropY[i] = -20
            dropX[i] = Math.random() * width * 1.2 - width * 0.1
          }
          const tail = scene.snow ? 1.5 : dropV[i] * 1.3
          ctx.moveTo(dropX[i], dropY[i])
          ctx.lineTo(dropX[i] - tail * lean, dropY[i] - tail)
        }
        ctx.stroke()
        ctx.globalAlpha = 1
      }

      const burst = !struck && t >= STRIKE
      ctx.globalCompositeOperation = 'lighter'
      ctx.lineWidth = 1.15 + settle * 0.35
      const shades = scene.palette.length
      for (let shade = 0; shade < shades; shade += 1) {
        ctx.strokeStyle = scene.palette[shade]
        ctx.globalAlpha = 0.55 + settle * 0.3
        ctx.beginPath()
        for (let i = shade; i < count; i += shades) {
          const px = x[i]
          const py = y[i]
          const town = i < towns
          const pinned = town ? smooth(MAP_IN + seed[i] * 0.6, MAP_HOLD - 0.5 + seed[i] * 0.6, t) * (1 - smooth(MAP_OUT, MAP_OUT + 0.25, t)) : 0
          const formed = smooth(EMBLEM_IN + seed[i] * 0.3, EMBLEM_SET - 0.3 + seed[i] * 0.3, t)
          const own = Math.max(pinned, formed)
          const goalX = formed > 0 ? tx[i] : mx[i]
          const goalY = formed > 0 ? ty[i] : my[i]
          const drift = 1 - release
          const turn =
            scene.angle +
            1.25 * Math.sin(px * wave + t * 0.7 + seed[i]) * Math.cos(py * wave * 1.3 - t * 0.5) +
            0.5 * Math.sin((px + py) * wave * 0.6 + t)
          const pace = scene.speed * scale * (2.2 + seed[i] * 2.4)
          const dx = px - cx
          const dy = py - cy
          const dist = Math.hypot(dx, dy) + 1
          const spin = scale * 8 * (0.55 + Math.min(1.5, 240 / dist))
          const pull = Math.max(-1, Math.min(1, (dist - eye) / eye)) * 3.6 * scale
          const wantX = drift * Math.cos(turn) * pace + swirl * ((-dy / dist) * spin - (dx / dist) * pull)
          const wantY = drift * Math.sin(turn) * pace + swirl * ((dx / dist) * spin - (dy / dist) * pull)
          vx[i] += (wantX - vx[i]) * 0.09 * step
          vy[i] += (wantY - vy[i]) * 0.09 * step
          let nx = px + vx[i] * step * (1 - own) + (goalX - px) * own * 0.17 * step
          let ny = py + vy[i] * step * (1 - own) + (goalY - py) * own * 0.17 * step
          if (own > 0.98) {
            nx += (Math.random() - 0.5) * 0.8
            ny += (Math.random() - 0.5) * 0.8
          }
          if (burst) {
            const push = (14 + Math.random() * 46) * scale
            const ox = tx[i] - cx
            const oy = ty[i] - cy
            const reach = Math.hypot(ox, oy) + 1
            nx += (ox / reach) * push
            ny += (oy / reach) * push
          }
          if (own === 0 && swirl === 0 && (nx < -20 || nx > width + 20 || ny < -20 || ny > height + 20)) {
            x[i] = nx < -20 ? width + 20 : nx > width + 20 ? -20 : nx
            y[i] = ny < -20 ? height + 20 : ny > height + 20 ? -20 : ny
            continue
          }
          ctx.moveTo(px, py)
          ctx.lineTo(nx, ny)
          x[i] = nx
          y[i] = ny
        }
        ctx.stroke()
      }
      ctx.globalAlpha = 1

      if (charted > 0.01) drawMap(t, charted)

      if (swirl > 0.05 && settle < 0.6) {
        const glow = hud.createRadialGradient(cx, cy, 0, cx, cy, eye * 3)
        glow.addColorStop(0, `rgba(${BACKDROP}, ${0.9 * swirl})`)
        glow.addColorStop(0.3, `rgba(${BACKDROP}, ${0.5 * swirl})`)
        glow.addColorStop(1, `rgba(${BACKDROP}, 0)`)
        hud.fillStyle = glow
        hud.fillRect(cx - eye * 3, cy - eye * 3, eye * 6, eye * 6)
      }

      const age = t - STRIKE
      if (age >= 0) {
        const flicker = age < 0.06 ? 1 : age < 0.1 ? 0.2 : age < 0.17 ? 0.9 : Math.max(0, 1 - (age - 0.17) / 0.32)
        if (flicker > 0) {
          const bolt = bolts[age < 0.1 ? 0 : 1]
          hud.shadowColor = '#9fd1ff'
          hud.shadowBlur = 28
          hud.strokeStyle = '#ffffff'
          hud.globalAlpha = flicker
          hud.lineWidth = 3
          trace(hud, bolt.trunk)
          hud.lineWidth = 1.3
          for (const branch of bolt.branches) trace(hud, branch)
          hud.shadowBlur = 0
        }
        for (let wave2 = 0; wave2 < 2; wave2 += 1) {
          const ring = (age - wave2 * 0.12) / 0.7
          if (ring > 0 && ring < 1) {
            hud.globalAlpha = (1 - ring) * 0.7
            hud.strokeStyle = scene.palette[wave2 === 0 ? 3 : 0]
            hud.lineWidth = 2.6 * (1 - ring) + 0.4
            hud.beginPath()
            hud.arc(cx, cy, mark * (0.3 + ring * 1.7), 0, TAU)
            hud.stroke()
          }
        }
        hud.globalAlpha = 1
        if (flash.current) flash.current.style.opacity = String(flicker * 0.5)
        const shake = age < 0.35 ? 9 * (1 - age / 0.35) : 0
        const jolt = shake ? `translate(${(Math.random() - 0.5) * shake}px, ${(Math.random() - 0.5) * shake}px)` : ''
        board.style.transform = jolt
        glass.style.transform = jolt
        if (degrees.current && scene.temperature !== null) {
          const text = `${Math.round(scene.temperature * smooth(0.1, 0.75, age))}°`
          if (text !== shown) {
            shown = text
            degrees.current.textContent = text
          }
        }
      }

      if (burst) {
        struck = true
        setPhase('struck')
      }
      if (t >= REVEAL) {
        if (!leaving) {
          leaving = true
          setPhase('leaving')
        }
        const open = smooth(REVEAL, END, t)
        const radius = open * open * far
        const mask = `radial-gradient(circle at ${cx}px ${cy}px, transparent ${Math.max(0, radius - 70)}px, #000 ${radius}px)`
        host.style.maskImage = mask
        host.style.webkitMaskImage = mask
      }
      if (t >= END) {
        finish()
        return
      }
      frame = requestAnimationFrame(draw)
    }
    frame = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(frame)
      window.clearTimeout(guard)
      host.removeEventListener('pointerdown', skip)
      host.style.maskImage = ''
      host.style.webkitMaskImage = ''
    }
  }, [scene, size])

  if (gone) return null

  return (
    <div ref={root} className={`intro ${phase}`} role="presentation">
      <canvas ref={canvas} className="intro-canvas" />
      <div className="intro-sky" style={{ background: `radial-gradient(120% 80% at 50% 110%, rgba(${scene.tint}, 0.34) 0%, rgba(${scene.tint}, 0.1) 45%, transparent 75%)` }} />
      <canvas ref={overlay} className="intro-canvas" />
      <div className="intro-glow" />
      <div className="intro-mark" style={{ width: size, height: size }}>
        <LogoMark size={size} />
      </div>
      <div className="intro-title" style={{ top: `calc(42% + ${size / 2 + 14}px)` }}>
        <Wordmark size={Math.round(size * 0.2)} />
        <span className="intro-caption">
          {scene.place && <span>{scene.place.name}</span>}
          {scene.temperature !== null && <span ref={degrees} className="intro-degrees" />}
          {scene.caption && <span>{scene.caption}</span>}
        </span>
      </div>
      <div ref={flash} className="intro-flash" />
    </div>
  )
}
