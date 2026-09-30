const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface Continuous {
  mae: number
  bias: number
  rmse: number
  n: number
}

export interface Categorical {
  pod: number | null
  far: number | null
  csi: number | null
  hss: number | null
  observed_rain_hours: number
  n: number
}

export interface ModelScores {
  temp: Record<string, Continuous | null>
  dew: Record<string, Continuous | null>
  wind: Record<string, Continuous | null>
  rain: Record<string, Categorical | null>
}

export interface VerifyStation {
  icao: string
  iata: string | null
  name: string
  city: string | null
  lat: number
  lon: number
  km: number
  observations: number
  scores: Record<string, ModelScores>
  series: { time: string[]; observed: (number | null)[]; rain: (boolean | null)[]; models: Record<string, (number | null)[]> }
}

export interface BoardRow {
  model: string
  label: string
  rank: number
  temp_mae: number | null
  dew_mae: number | null
  wind_mae: number | null
  rain_hss: number | null
  index: number | null
}

export interface Scorecard {
  generated: string
  days: number
  stations: VerifyStation[]
  leaderboard: BoardRow[]
  best: BoardRow | null
  models: { model: string; label: string }[]
  method: string
}

export async function fetchScorecard(lat: number, lon: number, days: number): Promise<Scorecard> {
  const response = await fetch(`${BASE}/api/verify?lat=${lat}&lon=${lon}&days=${days}`)
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `Verification failed (${response.status})`)
  return response.json() as Promise<Scorecard>
}

export const MODEL_COLORS: Record<string, string> = {
  best_match: '#ff9933',
  ecmwf_ifs025: '#6fb7ff',
  gfs_seamless: '#c4b3ff',
  icon_seamless: '#5fd39a',
}
