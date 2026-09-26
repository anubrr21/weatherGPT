export type Sky = 'clear' | 'partly' | 'overcast' | 'fog' | 'drizzle' | 'rain' | 'heavy_rain' | 'snow' | 'thunder'

export interface Condition {
  label: string
  sky: Sky
}

export interface Place {
  name: string
  district?: string | null
  state?: string | null
  country?: string | null
  country_code?: string | null
  lat: number
  lon: number
  elevation?: number | null
}

export interface Current {
  time: string
  temperature_2m: number
  relative_humidity_2m: number
  apparent_temperature: number
  is_day: number
  precipitation: number
  weather_code: number
  cloud_cover: number
  pressure_msl: number
  wind_speed_10m: number
  wind_direction_10m: number
  wind_gusts_10m: number
  uv_index: number
  dew_point_2m: number
  condition: Condition
  wind_compass: string
}

export interface Hour {
  time: string
  temperature_2m: number
  apparent_temperature: number
  precipitation_probability: number | null
  precipitation: number
  weather_code: number
  wind_speed_10m: number
  wind_gusts_10m: number
  wind_direction_10m: number
  relative_humidity_2m: number
  cloud_cover: number
  visibility: number | null
  cape: number | null
  is_day: number
  uv_index: number | null
  condition: Condition
}

export interface Day {
  time: string
  weather_code: number
  temperature_2m_max: number
  temperature_2m_min: number
  apparent_temperature_max: number
  precipitation_sum: number
  precipitation_probability_max: number | null
  precipitation_hours: number
  wind_speed_10m_max: number
  wind_gusts_10m_max: number
  wind_direction_10m_dominant: number
  uv_index_max: number | null
  sunrise: string
  sunset: string
  shortwave_radiation_sum: number
  et0_fao_evapotranspiration: number
  condition: Condition
}

export interface Confidence {
  date: string
  score: number
  label: 'High' | 'Medium' | 'Low'
  spread_tmax: number | null
  spread_rain: number | null
  rain_agreement: string
}

export interface Observation {
  station: string
  name: string
  distance_km: number
  age_min: number | null
  temp_c: number
  dewpoint_c: number | null
  humidity_pct: number | null
  wind_kmh: number | null
  wind_dir: number | string | null
  weather: string | null
  raw: string
  source: string
}

export interface Forecast {
  observed?: Observation | null
  confidence?: Confidence[]
  model: string
  model_name: string
  timezone: string
  utc_offset_seconds: number
  elevation: number
  current: Current
  hourly: Hour[]
  daily: Day[]
}

export interface OfficialAlert {
  id: string
  source: string
  issuer?: string | null
  sender?: string | null
  sent?: string | null
  event?: string | null
  severity: string
  urgency?: string | null
  certainty?: string | null
  headline: string
  instruction?: string | null
  effective?: string | null
  expires?: string | null
  areas: string[]
  localized: { language: string | null; headline: string | null }[]
  match?: 'district' | 'state'
}

export interface DerivedAdvisory {
  date: string
  event: string
  severity: string
  detail: string
  source: string
}

export interface AlertsBundle {
  place?: Place
  official: OfficialAlert[]
  derived: DerivedAdvisory[]
}

export interface ClimateData {
  period: string
  source: string
  annual: { year: number; mean_temp: number; hot_days_over_40: number; rain_total: number }[]
  annual_temp_trend_c_per_decade: number | null
  annual_rain_trend_mm_per_decade: number | null
  month: number
  month_by_year: { year: number; mean_temp: number; rain_total: number }[]
  month_normal_1991_2020: { mean_temp: number | null; rain_total: number | null }
}

export interface ModelCompare {
  models: Record<string, string>
  days: ({ date: string; spread_tmax: number | null; spread_rain: number | null } & Record<string, unknown>)[]
}

export interface AirData {
  current: Record<string, number>
  india_naqi: number | null
  india_naqi_band: string | null
  dominant: string | null
  pm2_5_24h_avg: number | null
  pm10_24h_avg: number | null
}

export interface MarineData {
  available: boolean
  reason?: string
  current?: Record<string, number>
  daily?: { time: string; wave_height_max: number; wave_period_max: number; swell_wave_height_max: number }[]
}

export interface AviationData {
  station: string
  available: boolean
  name?: string
  raw_metar?: string
  raw_taf?: string
  observed?: string
  temp_c?: number
  dewpoint_c?: number
  wind_dir?: number | string
  wind_kt?: number
  gust_kt?: number | null
  visibility?: number | string
  altimeter_hpa?: number
  flight_category?: string
  decoded?: {
    wind?: string
    visibility?: string
    weather: string[]
    clouds: string[]
    temp_dew?: string
    qnh?: string
    trend?: string
    hazards: string[]
  }
}

export interface SprayWindow {
  start: string
  end: string
  hours: number
}

export interface FarmData {
  spray: { windows: SprayWindow[]; rules: string; main_blocker: string | null }
  irrigation: {
    crop: string | null
    stage: string | null
    kc: number
    et0_7d_mm: number
    crop_water_need_7d_mm: number
    rain_7d_mm: number
    effective_rain_7d_mm: number
    deficit_mm: number
    next_useful_rain: string | null
    advice: string
    method: string
  }
  dry_spells: { from: string; to: string; days: number }[]
  livestock: { peak_thi: number; at: string; level: string }
  heavy_rain_days: string[]
  hourly: Hour[]
  daily: Day[]
}

export type Verdict = 'GO' | 'CAUTION' | 'NO-GO'

export interface FishingData {
  available: boolean
  now: Verdict
  wave_now_m: number | null
  gust_now_kmh: number | null
  days: { date: string; wave_max_m: number | null; gust_max_kmh: number | null; rain_mm: number | null; verdict: Verdict }[]
  official_sea_alerts: { headline: string; severity: string }[]
  rules: string
}

export interface UrbanData {
  heat_index_peak: { time: string; heat_index: number; band: string }
  heat_series: { time: string; heat_index: number }[]
  waterlogging_risk: 'low' | 'moderate' | 'high'
  max_hourly_rain_mm: number
  max_3h_rain_mm: number
  commutes: { slot: string; rain_prob: number; rain_mm: number; heat_index: number }[]
}

export interface Insight {
  kind: string
  title: string
  value: string
  detail: string
  tone: string
}

export type Role = 'general' | 'farmer' | 'fisher' | 'aviation' | 'urban' | 'disaster_manager' | 'researcher'

export interface CropEntry {
  name: string
  stage: string | null
}

export interface Profile {
  role: Role
  crops: CropEntry[]
  places: Place[]
  notes: string[]
}

export interface ProfilePatch {
  role?: Role
  crops?: CropEntry[]
  save_place?: Place
  note?: string
}

export type Card =
  | { kind: 'forecast'; place: Place; data: Forecast }
  | { kind: 'alerts'; place: Place; data: AlertsBundle }
  | { kind: 'climate'; place: Place; data: ClimateData }
  | { kind: 'models'; place: Place; data: ModelCompare }
  | { kind: 'air'; place: Place; data: AirData }
  | { kind: 'marine'; place: Place; data: MarineData }
  | { kind: 'aviation'; place: Place; data: AviationData }
  | { kind: 'farm'; place: Place; data: FarmData }
  | { kind: 'fishing'; place: Place; data: FishingData }
  | { kind: 'urban'; place: Place; data: UrbanData }

export type ChatEvent =
  | { type: 'status'; text: string; tool: string; args: Record<string, unknown> }
  | { type: 'card'; card: Card }
  | { type: 'profile'; patch: ProfilePatch }
  | { type: 'provider'; name: string; label: string; fallback: boolean }
  | { type: 'reset' }
  | { type: 'delta'; text: string }
  | { type: 'error'; text: string }
  | { type: 'done' }

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  cards: Card[]
  steps: string[]
  pending?: boolean
  error?: string
  provider?: { name: string; label: string; fallback: boolean }
}
