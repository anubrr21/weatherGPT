import type { Place, Profile, ProfilePatch, Role } from './types'

const KEY = 'weathergpt:profile:v1'

export const EMPTY_PROFILE: Profile = { role: 'general', crops: [], places: [], notes: [] }

export const ROLES: { id: Role; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'farmer', label: 'Farmer' },
  { id: 'fisher', label: 'Fisher' },
  { id: 'aviation', label: 'Aviation' },
  { id: 'urban', label: 'City' },
  { id: 'disaster_manager', label: 'Disaster mgmt' },
  { id: 'researcher', label: 'Researcher' },
]

export const CROPS = ['paddy', 'wheat', 'maize', 'cotton', 'sugarcane', 'groundnut', 'soybean', 'pulses', 'mustard', 'millets', 'vegetables', 'chilli', 'banana', 'mango']

export const STAGES = ['initial', 'development', 'mid', 'late']

export function loadProfile(): Profile {
  try {
    return { ...EMPTY_PROFILE, ...(JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<Profile>) }
  } catch {
    return EMPTY_PROFILE
  }
}

export function saveProfile(profile: Profile) {
  try {
    localStorage.setItem(KEY, JSON.stringify(profile))
  } catch {
    return
  }
}

const samePlace = (a: Place, b: Place) => Math.abs(a.lat - b.lat) < 0.01 && Math.abs(a.lon - b.lon) < 0.01

export function addPlace(profile: Profile, place: Place): Profile {
  if (profile.places.some((p) => samePlace(p, place))) return profile
  return { ...profile, places: [...profile.places, place].slice(-12) }
}

export function removePlace(profile: Profile, place: Place): Profile {
  return { ...profile, places: profile.places.filter((p) => !samePlace(p, place)) }
}

export function applyPatch(profile: Profile, patch: ProfilePatch): Profile {
  let next = { ...profile }
  if (patch.role) next.role = patch.role
  if (patch.crops?.length) {
    const byName = new Map(next.crops.map((c) => [c.name, c]))
    for (const c of patch.crops) byName.set(c.name, c)
    next.crops = [...byName.values()]
  }
  if (patch.save_place) next = addPlace(next, patch.save_place)
  if (patch.note && !next.notes.includes(patch.note)) next.notes = [...next.notes, patch.note].slice(-10)
  return next
}
