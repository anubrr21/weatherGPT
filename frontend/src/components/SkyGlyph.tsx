import { Cloud, CloudDrizzle, CloudFog, CloudLightning, CloudRain, CloudRainWind, CloudSnow, CloudSun, Sun } from 'lucide-react'
import type { Sky } from '../lib/types'

const ICONS = {
  clear: Sun,
  partly: CloudSun,
  overcast: Cloud,
  fog: CloudFog,
  drizzle: CloudDrizzle,
  rain: CloudRain,
  heavy_rain: CloudRainWind,
  snow: CloudSnow,
  thunder: CloudLightning,
} satisfies Record<Sky, unknown>

export default function SkyGlyph({ sky, size = 18 }: { sky: Sky; size?: number }) {
  const Icon = ICONS[sky] ?? Cloud
  return <Icon size={size} strokeWidth={1.6} className={`glyph glyph-${sky}`} aria-hidden="true" />
}
