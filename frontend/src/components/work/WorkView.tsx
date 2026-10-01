import { Anchor, Building2, Database, Plane, Siren, Sprout, type LucideIcon } from 'lucide-react'
import type { Place, Profile, Role } from '../../lib/types'
import AviationView from './AviationView'
import CityView from './CityView'
import CommandView from './CommandView'
import DataView from './DataView'
import FarmView from './FarmView'
import SeaView from './SeaView'

interface Props {
  place: Place | null
  profile: Profile
  online: boolean
  language: string
  onAsk: (text: string) => void
  onEditProfile: () => void
}

export const WORK_ICONS: Partial<Record<Role, LucideIcon>> = {
  farmer: Sprout,
  fisher: Anchor,
  aviation: Plane,
  urban: Building2,
  disaster_manager: Siren,
  researcher: Database,
}

export default function WorkView({ place, profile, online, onAsk, onEditProfile }: Props) {
  if (profile.role === 'farmer') return <FarmView place={place} profile={profile} online={online} onAsk={onAsk} onEditProfile={onEditProfile} />
  if (profile.role === 'fisher') return <SeaView place={place} online={online} onAsk={onAsk} />
  if (profile.role === 'aviation') return <AviationView place={place} online={online} onAsk={onAsk} />
  if (profile.role === 'urban') return <CityView place={place} online={online} onAsk={onAsk} />
  if (profile.role === 'disaster_manager') return <CommandView place={place} online={online} onAsk={onAsk} />
  if (profile.role === 'researcher') return <DataView place={place} online={online} onAsk={onAsk} />
  return null
}
