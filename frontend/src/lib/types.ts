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

export interface Forecast {
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
}

export type Card =
  | { kind: 'forecast'; place: Place; data: Forecast }
  | { kind: 'alerts'; place: Place; data: AlertsBundle }
  | { kind: 'climate'; place: Place; data: ClimateData }
  | { kind: 'models'; place: Place; data: ModelCompare }
  | { kind: 'air'; place: Place; data: AirData }
  | { kind: 'marine'; place: Place; data: MarineData }
  | { kind: 'aviation'; place: Place; data: AviationData }

export type ChatEvent =
  | { type: 'status'; text: string; tool: string; args: Record<string, unknown> }
  | { type: 'card'; card: Card }
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
}
