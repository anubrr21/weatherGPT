const STOPS: [number, [number, number, number]][] = [
  [0, [120, 170, 255]],
  [12, [110, 210, 235]],
  [20, [140, 225, 170]],
  [27, [245, 215, 110]],
  [33, [255, 150, 80]],
  [40, [255, 80, 70]],
  [46, [200, 40, 110]],
]

export function tempColor(t: number, alpha = 1) {
  if (t <= STOPS[0][0]) return `rgba(${STOPS[0][1].join(',')},${alpha})`
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i]
    const [t0, c0] = STOPS[i - 1]
    if (t <= t1) {
      const k = (t - t0) / (t1 - t0)
      return `rgba(${c0.map((v, j) => Math.round(v + (c1[j] - v) * k)).join(',')},${alpha})`
    }
  }
  return `rgba(${STOPS[STOPS.length - 1][1].join(',')},${alpha})`
}

export const round = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : v.toFixed(digits)

export const hhmm = (iso: string) => iso.slice(11, 16)

export function hourLabel(iso: string) {
  const h = Number(iso.slice(11, 13))
  if (h === 0) return '12a'
  if (h === 12) return '12p'
  return h < 12 ? `${h}a` : `${h - 12}p`
}

export function weekday(iso: string, index: number) {
  if (index === 0) return 'Today'
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })
}

export function dayMonth(iso: string) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}

export function placeLabel(p: { name: string; district?: string | null; state?: string | null }) {
  return [p.name, p.district && p.district !== p.name ? p.district : null, p.state].filter(Boolean).join(', ')
}

export const SEVERITY_TONE: Record<string, string> = {
  Extreme: 'extreme',
  Severe: 'severe',
  Moderate: 'moderate',
  Minor: 'minor',
  Unknown: 'minor',
}
