import { MapPin, MessageSquareText, RefreshCw, UserRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AlertRibbon from './components/AlertRibbon'
import Chat from './components/Chat'
import DayStrip from './components/DayStrip'
import Hud from './components/Hud'
import InsightStrip from './components/InsightStrip'
import LocationSearch from './components/LocationSearch'
import ProfileSheet from './components/ProfileSheet'
import SkyCanvas from './components/SkyCanvas'
import TimeDial from './components/TimeDial'
import { api, streamChat, type Health } from './lib/api'
import { applyPatch, loadProfile, saveProfile } from './lib/profile'
import { unlockAudio } from './lib/voice'
import { momentAt, skyFor } from './lib/sky'
import type { AlertsBundle, ChatEvent, Forecast, Insight, Message, Place, Profile } from './lib/types'

const FALLBACK: Place = { name: 'Amaravati', district: 'Guntur', state: 'Andhra Pradesh', lat: 16.514, lon: 80.516 }
const STORE = 'weathergpt:v1'

interface Saved {
  place?: Place
  language?: string
}

function load(): Saved {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? '{}') as Saved
  } catch {
    return {}
  }
}

function save(patch: Saved) {
  try {
    localStorage.setItem(STORE, JSON.stringify({ ...load(), ...patch }))
  } catch {
    return
  }
}

const uid = () => Math.random().toString(36).slice(2, 10)

const INSIGHT_QUESTIONS: Record<string, string> = {
  spray: 'When can I safely spray pesticide in the next two days?',
  irrigation: 'Should I irrigate my crop this week, and how much?',
  dry: 'Is there a dry spell coming for harvesting and drying my produce?',
  sea: 'Is it safe to take the boat out today and this week?',
  heat: 'How hot will it feel today and how do I stay safe?',
  flood: 'Is there any risk of waterlogging in my area?',
  commute: 'What will the weather be like for my commute?',
  day: 'What is the weather today and tomorrow?',
}

export default function App() {
  const saved = useMemo(load, [])
  const [place, setPlace] = useState<Place | null>(saved.place ?? null)
  const [usingDevice, setUsingDevice] = useState(!saved.place)
  const [fc, setFc] = useState<Forecast | null>(null)
  const [alerts, setAlerts] = useState<AlertsBundle | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [hour, setHour] = useState<number | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [language, setLanguage] = useState(saved.language ?? 'en')
  const [messages, setMessages] = useState<Message[]>([])
  const [busy, setBusy] = useState(false)
  const [llm, setLlm] = useState<Health | null>(null)
  const [profile, setProfileState] = useState<Profile>(loadProfile)
  const [profileOpen, setProfileOpen] = useState(false)
  const [insights, setInsights] = useState<Insight[] | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const locate = useCallback(() => {
    setSearchOpen(false)
    if (!navigator.geolocation) {
      setPlace((p) => p ?? FALLBACK)
      return
    }
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude: lat, longitude: lon } = pos.coords
        setUsingDevice(true)
        save({ place: undefined })
        setPlace({ name: 'Locating…', lat, lon })
        try {
          setPlace(await api.reverse(lat, lon))
        } catch {
          setPlace({ name: `${lat.toFixed(2)}°, ${lon.toFixed(2)}°`, lat, lon })
        }
      },
      () => setPlace((p) => p ?? FALLBACK),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 },
    )
  }, [])

  useEffect(() => {
    const unlock = () => unlockAudio()
    window.addEventListener('pointerdown', unlock, { once: true })
    window.addEventListener('keydown', unlock, { once: true })
    return () => {
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    }
  }, [])

  useEffect(() => {
    api.health().then(setLlm).catch(() => setLlm({ ok: false, llm: false, providers: [] }))
    if (!saved.place) locate()
  }, [])

  const refresh = useCallback(() => {
    if (!place) return
    setLoadError(null)
    api
      .forecast(place.lat, place.lon)
      .then((data) => {
        setFc(data)
        setHour(null)
      })
      .catch((e: Error) => setLoadError(e.message))
    api.alerts(place.lat, place.lon).then(setAlerts).catch(() => setAlerts(null))
  }, [place?.lat, place?.lon])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 10 * 60 * 1000)
    return () => clearInterval(id)
  }, [refresh])

  const setProfile = useCallback((next: Profile | ((p: Profile) => Profile)) => {
    setProfileState((prev) => {
      const value = typeof next === 'function' ? next(prev) : next
      saveProfile(value)
      return value
    })
  }, [])

  const insightKey = `${profile.role}:${profile.crops[0]?.name ?? ''}:${profile.crops[0]?.stage ?? ''}`
  useEffect(() => {
    if (!place || !fc) return
    api.insights(place.lat, place.lon, profile).then(setInsights).catch(() => setInsights(null))
  }, [place?.lat, place?.lon, fc?.current.time, insightKey])

  const moment = fc ? momentAt(fc, hour) : null
  const sky = fc && moment ? skyFor(fc, moment) : null

  const patchLast = (fn: (m: Message) => Message) =>
    setMessages((all) => (all.length ? [...all.slice(0, -1), fn(all[all.length - 1])] : all))

  const send = useCallback(
    async (text: string) => {
      if (busy) return
      setChatOpen(true)
      const history = messages.filter((m) => !m.pending && m.text).map((m) => ({ role: m.role, text: m.text }))
      setMessages((all) => [
        ...all,
        { id: uid(), role: 'user', text, cards: [], steps: [] },
        { id: uid(), role: 'assistant', text: '', cards: [], steps: [], pending: true },
      ])
      setBusy(true)
      const controller = new AbortController()
      abortRef.current = controller
      const onEvent = (e: ChatEvent) => {
        if (e.type === 'status') patchLast((m) => ({ ...m, steps: [...m.steps, e.text] }))
        else if (e.type === 'card') patchLast((m) => ({ ...m, cards: [...m.cards, e.card] }))
        else if (e.type === 'delta') patchLast((m) => ({ ...m, text: m.text + e.text }))
        else if (e.type === 'error') patchLast((m) => ({ ...m, error: e.text }))
        else if (e.type === 'profile') setProfile((p) => applyPatch(p, e.patch))
        else if (e.type === 'provider') patchLast((m) => ({ ...m, provider: { name: e.name, label: e.label, fallback: e.fallback } }))
        else if (e.type === 'reset') patchLast((m) => ({ ...m, text: '', cards: [], steps: [] }))
      }
      try {
        await streamChat(
          {
            message: text,
            history,
            lat: place?.lat,
            lon: place?.lon,
            place_name: place?.name,
            language,
            profile,
          },
          onEvent,
          controller.signal,
        )
      } catch (err) {
        if ((err as Error).name !== 'AbortError') patchLast((m) => ({ ...m, error: (err as Error).message }))
      } finally {
        patchLast((m) => ({ ...m, pending: false }))
        setBusy(false)
      }
    },
    [busy, messages, place, language, profile],
  )

  const subtitle = place
    ? [place.district !== place.name ? place.district : null, place.state].filter(Boolean).join(', ') || (usingDevice ? 'Current location' : '')
    : ''

  return (
    <div className={`app ${chatOpen ? 'chat-open' : ''}`}>
      <SkyCanvas target={sky} />

      <main className="stage">
        <header className="topbar">
          <button className="place" onClick={() => setSearchOpen(true)}>
            <MapPin size={16} />
            <span>
              <b>{place?.name ?? 'Locating…'}</b>
              <small>{subtitle}</small>
            </span>
          </button>
          <button className="icon-btn glass" onClick={refresh} aria-label="Refresh">
            <RefreshCw size={16} />
          </button>
          <button className={`icon-btn glass ${profile.role !== 'general' ? 'active' : ''}`} onClick={() => setProfileOpen(true)} aria-label="Your profile">
            <UserRound size={17} />
          </button>
        </header>

        {loadError && (
          <div className="ribbon severe">
            <span>Could not load forecast: {loadError}. Is the backend running on port 8000?</span>
          </div>
        )}

        {fc && moment ? (
          <>
            <Hud fc={fc} m={moment} />
            <AlertRibbon bundle={alerts} onAsk={send} />
            <InsightStrip items={insights} onAsk={(kind) => send(INSIGHT_QUESTIONS[kind] ?? INSIGHT_QUESTIONS.day)} />
            <TimeDial hours={fc.hourly} selected={hour} onSelect={setHour} />
            <DayStrip days={fc.daily} />
          </>
        ) : (
          !loadError && (
            <div className="boot">
              <span className="boot-orb" />
              Reading the atmosphere…
            </div>
          )
        )}

        <button className="ask-fab" onClick={() => setChatOpen(true)}>
          <MessageSquareText size={18} />
          Ask WeatherGPT
        </button>
      </main>

      <aside className="chat-dock">
        <Chat
          messages={messages}
          busy={busy}
          language={language}
          llm={llm}
          onLanguage={(code) => {
            setLanguage(code)
            save({ language: code })
          }}
          onSend={(t) => send(t)}
          onStop={() => abortRef.current?.abort()}
          onCollapse={() => setChatOpen(false)}
        />
      </aside>

      {profileOpen && (
        <ProfileSheet
          profile={profile}
          current={place}
          onChange={setProfile}
          onClose={() => setProfileOpen(false)}
          onPickPlace={(p) => {
            setPlace(p)
            setUsingDevice(false)
            save({ place: p })
            setProfileOpen(false)
          }}
        />
      )}

      {searchOpen && (
        <LocationSearch
          saved={profile.places}
          onClose={() => setSearchOpen(false)}
          onLocate={locate}
          onPick={(p) => {
            setPlace(p)
            setUsingDevice(false)
            save({ place: p })
            setSearchOpen(false)
          }}
        />
      )}
    </div>
  )
}
