import { Anchor, Sprout, type LucideIcon } from 'lucide-react'
import type { Place, Profile, Role } from '../../lib/types'
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
}

export default function WorkView({ place, profile, online, onAsk, onEditProfile }: Props) {
  if (profile.role === 'farmer') return <FarmView place={place} profile={profile} online={online} onAsk={onAsk} onEditProfile={onEditProfile} />
  if (profile.role === 'fisher') return <SeaView place={place} online={online} onAsk={onAsk} />
  return null
}
