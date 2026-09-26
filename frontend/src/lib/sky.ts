import type { Forecast, Sky } from './types'

export interface SkyState {
  sky: Sky
  sun: number
  sunX: number
  cloud: number
  rain: number
  snow: boolean
  thunder: boolean
  fog: number
  windX: number
  windSpeed: number
}

export interface Moment {
  time: string
  temperature: number
  feelsLike: number
  humidity: number
  windSpeed: number
  windDir: number
  gust: number
  cloud: number
  precip: number
  precipProb: number | null
  uv: number | null
  label: string
  sky: Sky
  live: boolean
}

const minutesOf = (iso: string) => {
  const [h, m] = iso.slice(11, 16).split(':').map(Number)
  return h * 60 + m
}

export function momentAt(fc: Forecast, hourIndex: number | null): Moment {
  if (hourIndex === null) {
    const c = fc.current
    return {
      time: c.time,
      temperature: c.temperature_2m,
      feelsLike: c.apparent_temperature,
      humidity: c.relative_humidity_2m,
      windSpeed: c.wind_speed_10m,
      windDir: c.wind_direction_10m,
      gust: c.wind_gusts_10m,
      cloud: c.cloud_cover,
      precip: c.precipitation,
      precipProb: fc.hourly[0]?.precipitation_probability ?? null,
      uv: c.uv_index,
      label: c.condition.label,
      sky: c.condition.sky,
      live: true,
    }
  }
  const h = fc.hourly[hourIndex]
  return {
    time: h.time,
    temperature: h.temperature_2m,
    feelsLike: h.apparent_temperature,
    humidity: h.relative_humidity_2m,
    windSpeed: h.wind_speed_10m,
    windDir: h.wind_direction_10m,
    gust: h.wind_gusts_10m,
    cloud: h.cloud_cover,
    precip: h.precipitation,
    precipProb: h.precipitation_probability,
    uv: h.uv_index,
    label: h.condition.label,
    sky: h.condition.sky,
    live: false,
  }
}

export function skyFor(fc: Forecast, m: Moment): SkyState {
  const day = fc.daily.find((d) => d.time === m.time.slice(0, 10)) ?? fc.daily[0]
  const rise = minutesOf(day.sunrise)
  const set = minutesOf(day.sunset)
  const now = minutesOf(m.time)
  const span = Math.max(set - rise, 1)
  const t = (now - rise) / span
  let sun: number
  if (t >= 0 && t <= 1) sun = Math.sin(Math.PI * t)
  else {
    const nightSpan = 1440 - span
    const into = t > 1 ? now - set : now + 1440 - set
    sun = -Math.sin(Math.PI * Math.min(Math.max(into / nightSpan, 0), 1))
  }
  const rainBySky: Partial<Record<Sky, number>> = { drizzle: 0.25, rain: 0.55, heavy_rain: 0.95, thunder: 0.8 }
  const rainFromMm = Math.min(m.precip / 8, 1)
  const toward = ((m.windDir + 180) % 360) * (Math.PI / 180)
  return {
    sky: m.sky,
    sun,
    sunX: Math.min(Math.max(t, -0.1), 1.1),
    cloud: Math.max(m.cloud / 100, m.sky === 'overcast' ? 0.9 : 0, ['rain', 'heavy_rain', 'thunder'].includes(m.sky) ? 0.85 : 0),
    rain: Math.max(rainBySky[m.sky] ?? 0, m.sky === 'snow' ? 0 : rainFromMm),
    snow: m.sky === 'snow',
    thunder: m.sky === 'thunder',
    fog: m.sky === 'fog' ? 0.75 : m.humidity > 95 ? 0.25 : 0,
    windX: Math.sin(toward),
    windSpeed: m.windSpeed,
  }
}

type RGB = [number, number, number]

const mix = (a: RGB, b: RGB, k: number): RGB => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k]
const grey = (c: RGB, k: number): RGB => {
  const l = c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11
  return mix(c, [l, l, l], k)
}
export const rgb = (c: RGB, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`

const NIGHT: [RGB, RGB] = [[6, 10, 28], [20, 30, 62]]
const TWILIGHT: [RGB, RGB] = [[40, 48, 102], [255, 140, 90]]
const DAY: [RGB, RGB] = [[36, 104, 196], [150, 205, 240]]

export function skyGradient(s: SkyState): [RGB, RGB] {
  let top: RGB
  let bottom: RGB
  if (s.sun <= -0.2) [top, bottom] = NIGHT
  else if (s.sun < 0.15) {
    const k = (s.sun + 0.2) / 0.35
    top = mix(NIGHT[0], TWILIGHT[0], k)
    bottom = mix(NIGHT[1], TWILIGHT[1], k)
  } else if (s.sun < 0.45) {
    const k = (s.sun - 0.15) / 0.3
    top = mix(TWILIGHT[0], DAY[0], k)
    bottom = mix(TWILIGHT[1], DAY[1], k)
  } else [top, bottom] = DAY
  const gloom = Math.min(s.cloud * 0.7 + s.rain * 0.35 + (s.thunder ? 0.2 : 0), 0.92)
  const darken = 1 - Math.min(s.rain * 0.35 + (s.thunder ? 0.25 : 0), 0.55)
  top = grey(top, gloom).map((v) => v * darken) as RGB
  bottom = grey(bottom, gloom).map((v) => v * darken) as RGB
  return [top, bottom]
}
