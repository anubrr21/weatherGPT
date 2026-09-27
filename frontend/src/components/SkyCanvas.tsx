import { useEffect, useRef } from 'react'
import { rgb, skyGradient, type SkyState } from '../lib/sky'

interface Cloud {
  x: number
  y: number
  r: number
  layer: number
  puffs: { dx: number; dy: number; r: number }[]
}

interface Drop {
  x: number
  y: number
  len: number
  speed: number
}

interface Star {
  x: number
  y: number
  r: number
  phase: number
}

const lerp = (a: number, b: number, k: number) => a + (b - a) * k

function makeCloud(w: number, h: number, layer: number, x?: number): Cloud {
  const r = (40 + Math.random() * 70) * (0.6 + layer * 0.4) * Math.max(w / 900, 0.7)
  const puffs = Array.from({ length: 5 + Math.floor(Math.random() * 5) }, () => ({
    dx: (Math.random() - 0.5) * r * 2.6,
    dy: (Math.random() - 0.6) * r * 0.7,
    r: r * (0.45 + Math.random() * 0.6),
  }))
  return { x: x ?? Math.random() * w, y: h * (0.05 + Math.random() * 0.4 + layer * 0.08), r, layer, puffs }
}

function boltPath(x: number, h: number) {
  const pts: [number, number][] = [[x, 0]]
  let cx = x
  let cy = 0
  while (cy < h * 0.75) {
    cy += 18 + Math.random() * 38
    cx += (Math.random() - 0.5) * 60
    pts.push([cx, cy])
  }
  return pts
}

export default function SkyCanvas({ target, lite = false }: { target: SkyState | null; lite?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const targetRef = useRef<SkyState | null>(target)
  targetRef.current = target

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const reduced = lite || window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let w = 0
    let h = 0
    let clouds: Cloud[] = []
    let drops: Drop[] = []
    let stars: Star[] = []
    let flash = 0
    let bolt: [number, number][] | null = null
    let nextStrike = 2 + Math.random() * 4
    let raf = 0
    let timer = 0
    let last = performance.now()
    let state: SkyState | null = null

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      clouds = Array.from({ length: 16 }, (_, i) => makeCloud(w, h, i % 3))
      drops = Array.from({ length: Math.round((w * h) / 2600) }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        len: 10 + Math.random() * 18,
        speed: 600 + Math.random() * 500,
      }))
      stars = Array.from({ length: Math.round((w * h) / 5000) }, () => ({
        x: Math.random() * w,
        y: Math.random() * h * 0.7,
        r: Math.random() * 1.3 + 0.2,
        phase: Math.random() * Math.PI * 2,
      }))
    }

    const blend = (to: SkyState, k: number): SkyState =>
      state
        ? {
            ...to,
            sun: lerp(state.sun, to.sun, k),
            sunX: lerp(state.sunX, to.sunX, k),
            cloud: lerp(state.cloud, to.cloud, k),
            rain: lerp(state.rain, to.rain, k),
            fog: lerp(state.fog, to.fog, k),
            windX: lerp(state.windX, to.windX, k),
            windSpeed: lerp(state.windSpeed, to.windSpeed, k),
          }
        : to

    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.05)
      last = now
      const to = targetRef.current
      if (to) state = blend(to, 1 - Math.pow(0.02, dt))
      const s = state
      if (!s) {
        raf = requestAnimationFrame(frame)
        return
      }
      const [top, bottom] = skyGradient(s)
      const g = ctx.createLinearGradient(0, 0, 0, h)
      g.addColorStop(0, rgb(top))
      g.addColorStop(1, rgb(bottom))
      ctx.fillStyle = g
      ctx.fillRect(0, 0, w, h)

      const starAlpha = Math.max(0, -s.sun - 0.05) * (1 - s.cloud)
      if (starAlpha > 0.01) {
        for (const st of stars) {
          const tw = 0.6 + 0.4 * Math.sin(now / 900 + st.phase)
          ctx.fillStyle = `rgba(255,255,255,${starAlpha * tw})`
          ctx.beginPath()
          ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      const bodyX = w * (0.1 + 0.8 * Math.min(Math.max(s.sunX, 0), 1))
      const isDay = s.sun > -0.08
      const bodyY = isDay ? h * (0.62 - 0.5 * Math.max(s.sun, 0)) : h * (0.18 + 0.2 * (1 + s.sun))
      const moonX = isDay ? -999 : w * 0.75
      const veil = 1 - s.cloud * 0.85
      if (isDay) {
        const warm = Math.max(0, 1 - s.sun * 2)
        const halo = ctx.createRadialGradient(bodyX, bodyY, 0, bodyX, bodyY, Math.max(w, h) * 0.55)
        halo.addColorStop(0, `rgba(255,${200 - warm * 60},${140 - warm * 70},${0.55 * veil})`)
        halo.addColorStop(0.15, `rgba(255,${180 - warm * 60},${110 - warm * 60},${0.18 * veil})`)
        halo.addColorStop(1, 'rgba(255,160,90,0)')
        ctx.fillStyle = halo
        ctx.fillRect(0, 0, w, h)
        ctx.fillStyle = `rgba(255,${246 - warm * 40},${220 - warm * 80},${0.95 * veil})`
        ctx.beginPath()
        ctx.arc(bodyX, bodyY, 26, 0, Math.PI * 2)
        ctx.fill()
      } else {
        const glow = ctx.createRadialGradient(moonX, bodyY, 0, moonX, bodyY, 160)
        glow.addColorStop(0, `rgba(200,215,255,${0.25 * veil})`)
        glow.addColorStop(1, 'rgba(200,215,255,0)')
        ctx.fillStyle = glow
        ctx.fillRect(0, 0, w, h)
        ctx.fillStyle = `rgba(232,236,250,${0.9 * veil})`
        ctx.beginPath()
        ctx.arc(moonX, bodyY, 18, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = rgb(top, veil)
        ctx.beginPath()
        ctx.arc(moonX + 8, bodyY - 5, 16, 0, Math.PI * 2)
        ctx.fill()
      }

      const drift = (8 + s.windSpeed * 1.4) * (s.windX >= 0 ? 1 : -1) * Math.max(Math.abs(s.windX), 0.35)
      const visible = Math.round(clouds.length * Math.min(s.cloud * 1.1, 1))
      const lit = Math.max(s.sun, 0)
      for (let i = 0; i < visible; i++) {
        const c = clouds[i]
        c.x += drift * dt * (0.5 + c.layer * 0.35)
        const span = c.r * 3
        if (c.x > w + span) c.x = -span
        if (c.x < -span) c.x = w + span
        const base = s.rain > 0.3 ? 70 + lit * 60 : 140 + lit * 110
        const shade = Math.min(base + c.layer * 12, 255)
        const alpha = (0.35 + c.layer * 0.18) * (0.6 + s.cloud * 0.4)
        for (const p of c.puffs) {
          const px = c.x + p.dx
          const py = c.y + p.dy
          const cg = ctx.createRadialGradient(px, py - p.r * 0.3, p.r * 0.1, px, py, p.r)
          cg.addColorStop(0, `rgba(${shade},${shade},${Math.min(shade + 10, 255)},${alpha})`)
          cg.addColorStop(1, `rgba(${shade * 0.8},${shade * 0.8},${shade * 0.85},0)`)
          ctx.fillStyle = cg
          ctx.beginPath()
          ctx.arc(px, py, p.r, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      if (s.rain > 0.02 && !s.snow) {
        const count = Math.round(drops.length * s.rain)
        const slant = s.windX * Math.min(s.windSpeed / 25, 1) * 0.45
        ctx.strokeStyle = `rgba(190,215,255,${0.25 + s.rain * 0.3})`
        ctx.lineWidth = 1
        ctx.beginPath()
        for (let i = 0; i < count; i++) {
          const d = drops[i]
          d.y += d.speed * dt
          d.x += d.speed * slant * dt
          if (d.y > h) {
            d.y = -d.len
            d.x = Math.random() * w
          }
          if (d.x > w) d.x -= w
          if (d.x < 0) d.x += w
          ctx.moveTo(d.x, d.y)
          ctx.lineTo(d.x - d.len * slant, d.y - d.len)
        }
        ctx.stroke()
      }

      if (s.snow) {
        ctx.fillStyle = 'rgba(255,255,255,0.8)'
        for (let i = 0; i < drops.length * 0.6; i++) {
          const d = drops[i]
          d.y += d.speed * 0.08 * dt
          d.x += Math.sin(now / 700 + i) * 0.4 + s.windX * 0.5
          if (d.y > h) d.y = -4
          ctx.beginPath()
          ctx.arc(d.x % w, d.y, 1.6, 0, Math.PI * 2)
          ctx.fill()
        }
      }

      if (s.fog > 0.02) {
        for (let i = 0; i < 4; i++) {
          const y = h * (0.45 + i * 0.14)
          const fg = ctx.createLinearGradient(0, y - 80, 0, y + 80)
          fg.addColorStop(0, 'rgba(210,215,225,0)')
          fg.addColorStop(0.5, `rgba(210,215,225,${s.fog * 0.35})`)
          fg.addColorStop(1, 'rgba(210,215,225,0)')
          ctx.fillStyle = fg
          ctx.fillRect(0, y - 80, w, 160)
        }
      }

      if (s.thunder && !reduced) {
        nextStrike -= dt
        if (nextStrike <= 0) {
          flash = 1
          bolt = Math.random() < 0.6 ? boltPath(w * (0.15 + Math.random() * 0.7), h) : null
          nextStrike = 3 + Math.random() * 7
        }
      }
      if (flash > 0) {
        ctx.fillStyle = `rgba(220,230,255,${flash * 0.35})`
        ctx.fillRect(0, 0, w, h)
        if (bolt && flash > 0.4) {
          ctx.strokeStyle = `rgba(245,248,255,${flash})`
          ctx.lineWidth = 2
          ctx.shadowColor = 'rgba(180,200,255,1)'
          ctx.shadowBlur = 18
          ctx.beginPath()
          bolt.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
          ctx.stroke()
          ctx.shadowBlur = 0
        }
        flash = Math.max(0, flash - dt * (flash > 0.5 ? 2.5 : 1.2))
      }

      const vignette = ctx.createLinearGradient(0, h * 0.55, 0, h)
      vignette.addColorStop(0, 'rgba(5,8,18,0)')
      vignette.addColorStop(1, 'rgba(5,8,18,0.65)')
      ctx.fillStyle = vignette
      ctx.fillRect(0, 0, w, h)

      if (reduced) timer = window.setTimeout(() => (raf = requestAnimationFrame(frame)), 400)
      else raf = requestAnimationFrame(frame)
    }

    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(canvas)
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      clearTimeout(timer)
      observer.disconnect()
    }
  }, [lite])

  return <canvas ref={canvasRef} className="sky-canvas" aria-hidden="true" />
}
