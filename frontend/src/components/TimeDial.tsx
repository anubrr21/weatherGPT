import { useRef } from 'react'
import { hourLabel, round, tempColor } from '../lib/format'
import type { Hour } from '../lib/types'

const SIZE = 296
const C = SIZE / 2
const R_OUT = 118
const R_TEMP = 104
const R_DAY = 90
const R_RAIN = 84

const polar = (r: number, angle: number) => [C + r * Math.cos(angle), C + r * Math.sin(angle)] as const
const angleOf = (i: number) => (i / 24) * Math.PI * 2 - Math.PI / 2

function arc(r: number, a0: number, a1: number) {
  const [x0, y0] = polar(r, a0)
  const [x1, y1] = polar(r, a1)
  return `M ${x0} ${y0} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1} ${y1}`
}

interface Props {
  hours: Hour[]
  selected: number | null
  onSelect: (index: number | null) => void
}

export default function TimeDial({ hours, selected, onSelect }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const dragging = useRef(false)
  const ring = hours.slice(0, 24)
  const active = selected ?? 0
  const h = ring[active]

  const pick = (clientX: number, clientY: number) => {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    const x = ((clientX - box.left) / box.width) * SIZE - C
    const y = ((clientY - box.top) / box.height) * SIZE - C
    if (Math.hypot(x, y) < 55) return
    let a = Math.atan2(y, x) + Math.PI / 2
    if (a < 0) a += Math.PI * 2
    const index = Math.min(23, Math.floor((a / (Math.PI * 2)) * 24))
    onSelect(index === 0 ? null : index)
  }

  const knob = angleOf(active + 0.5)
  const [kx, ky] = polar(R_TEMP, knob)

  return (
    <div className="dial">
      <svg
        ref={ref}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        role="slider"
        aria-label="Scrub through the next 24 hours"
        aria-valuemin={0}
        aria-valuemax={23}
        aria-valuenow={active}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight' || e.key === 'ArrowUp') onSelect(Math.min(active + 1, 23))
          if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') onSelect(active - 1 <= 0 ? null : active - 1)
          if (e.key === 'Escape') onSelect(null)
        }}
        onPointerDown={(e) => {
          dragging.current = true
          ;(e.target as Element).setPointerCapture?.(e.pointerId)
          pick(e.clientX, e.clientY)
        }}
        onPointerMove={(e) => dragging.current && pick(e.clientX, e.clientY)}
        onPointerUp={() => (dragging.current = false)}
        onPointerCancel={() => (dragging.current = false)}
      >
        <circle cx={C} cy={C} r={R_OUT + 4} className="dial-bezel" />
        {ring.map((hr, i) => {
          const a0 = angleOf(i) + 0.012
          const a1 = angleOf(i + 1) - 0.012
          const prob = (hr.precipitation_probability ?? 0) / 100
          const [rx0, ry0] = polar(R_RAIN, angleOf(i + 0.5))
          const [rx1, ry1] = polar(R_RAIN - 4 - prob * 30, angleOf(i + 0.5))
          const [tx, ty] = polar(R_OUT + 12, angleOf(i + 0.5))
          return (
            <g key={hr.time}>
              <path d={arc(R_TEMP, a0, a1)} stroke={tempColor(hr.temperature_2m, i === active ? 1 : 0.78)} strokeWidth={i === active ? 16 : 11} fill="none" strokeLinecap="butt" />
              <path d={arc(R_DAY, a0, a1)} stroke={hr.is_day ? 'rgba(255,214,140,0.55)' : 'rgba(120,140,220,0.35)'} strokeWidth={3} fill="none" />
              {prob > 0.04 && <line x1={rx0} y1={ry0} x2={rx1} y2={ry1} stroke={`rgba(120,190,255,${0.35 + prob * 0.65})`} strokeWidth={4} strokeLinecap="round" />}
              {i % 3 === 0 && (
                <text x={tx} y={ty} className="dial-hour">
                  {hourLabel(hr.time)}
                </text>
              )}
            </g>
          )
        })}
        <circle cx={kx} cy={ky} r={10} className="dial-knob" />
        <g className="dial-center" onClick={() => onSelect(null)}>
          <circle cx={C} cy={C} r={52} />
          <text x={C} y={C - 14} className="dial-center-time">{selected === null ? 'NOW' : h?.time.slice(11, 16)}</text>
          <text x={C} y={C + 14} className="dial-center-temp">{round(h?.temperature_2m)}°</text>
          <text x={C} y={C + 32} className="dial-center-rain">{h?.precipitation_probability ?? 0}% rain</text>
        </g>
      </svg>
      <p className="dial-caption">{selected === null ? 'Drag the ring to see the sky later today' : 'Tap centre to return to live'}</p>
    </div>
  )
}
