import { MapPin, MessageSquareText, RefreshCw, UserRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AlertRibbon from './components/AlertRibbon'
import Chat from './components/Chat'
import DayStrip from './components/DayStrip'
import Hud from './components/Hud'
import InsightStrip from './components/InsightStrip'
import { AlertToasts, LiveBell } from './components/LiveAlerts'
import Logo, { LogoMark, Wordmark } from './components/Logo'
import LocationSearch from './components/LocationSearch'
import ProfileSheet from './components/ProfileSheet'
import RadarMap from './components/RadarMap'
import SkyCanvas from './components/SkyCanvas'
import TimeDial from './components/TimeDial'
import { api, streamChat, type Health } from './lib/api'
import { placeLabel } from './lib/format'
import { PlaceContext } from './lib/placeContext'
import { addPlace, applyPatch, loadProfile, removePlace, saveProfile } from './lib/profile'
import { syncSubscriptions, useLiveAlerts, type LiveAlert } from './lib/live'
import { initNative, notifyAlert, promptNotificationsOnce, type AlertTap } from './lib/native'
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

const INSIGHT_QUESTIONS: Record<string, (where: string) => string> = {
  spray: (where) => `When can I safely spray pesticide in ${where} in the next two days?`,
  irrigation: (where) => `Should I irrigate my crop in ${where} this week, and how much?`,
  dry: (where) => `Is there a dry spell coming in ${where} for harvesting and drying my produce?`,
  sea: (where) => `Is it safe to take the boat out from ${where} today and this week?`,
  heat: (where) => `How hot will it feel in ${where} today and how do I stay safe?`,
  flood: (where) => `Is there any risk of waterlogging in ${where}?`,
  commute: (where) => `What will the weather be like for my commute in ${where} today?`,
  day: (where) => `What is the weather in ${where} today and tomorrow?`,
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
  const [inbox, setInbox] = useState<LiveAlert[]>([])
  const [toasts, setToasts] = useState<LiveAlert[]>([])
  const [unread, setUnread] = useState(0)
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

  const liveState = useLiveAlerts((incoming) => {
    setInbox((all) => (all.some((a) => a.alert.id === incoming.alert.id) ? all : [incoming, ...all].slice(0, 50)))
    setToasts((all) => (all.some((a) => a.alert.id === incoming.alert.id) ? all : [incoming, ...all]))
    setUnread((n) => n + 1)
    notifyAlert(incoming)
    if (place && Math.abs(incoming.place.lat - place.lat) < 0.05 && Math.abs(incoming.place.lon - place.lon) < 0.05) {
      api.alerts(place.lat, place.lon).then(setAlerts).catch(() => undefined)
    }
  })

  const placesKey = JSON.stringify([place, ...profile.places].filter(Boolean).map((p) => [p!.lat.toFixed(3), p!.lon.toFixed(3)]))
  useEffect(() => {
    const places = [place, ...profile.places].filter((p): p is Place => Boolean(p) && (p as Place).name !== 'Locating…')
    if (!places.length) return
    const id = setTimeout(() => syncSubscriptions(places).catch(() => undefined), 800)
    return () => clearTimeout(id)
  }, [placesKey, liveState === 'live'])

  const askAboutAlert = (a: LiveAlert) =>
    send(`IMD has issued "${a.alert.event}" (${a.alert.severity}) for ${a.place.name}: ${a.alert.headline} What exactly should I do?`)

  const nativeRef = useRef<{ back: () => boolean; tap: (tap: AlertTap) => void | Promise<void> }>({ back: () => false, tap: () => undefined })
  nativeRef.current.back = () => {
    if (searchOpen) setSearchOpen(false)
    else if (profileOpen) setProfileOpen(false)
    else if (chatOpen) setChatOpen(false)
    else return false
    return true
  }
  nativeRef.current.tap = async (tap: AlertTap) => {
    try {
      const history = await api.alertHistory(tap.lat, tap.lon)
      const alert = history.alerts.find((a) => a.id === tap.alertId)
      setPlace(history.place)
      setUsingDevice(false)
      save({ place: history.place })
      setSearchOpen(false)
      setProfileOpen(false)
      if (alert) askAboutAlert({ receivedAt: Date.now(), place: { ...history.place, name: tap.place || history.place.name }, match: alert.match ?? 'district', alert })
    } catch {
      setPlace({ name: tap.place, lat: tap.lat, lon: tap.lon })
    }
  }

  useEffect(() => initNative({ onBack: () => nativeRef.current.back(), onAlertTap: (t) => nativeRef.current.tap(t) }), [])

  useEffect(() => {
    if (!fc) return
    const id = window.setTimeout(() => void promptNotificationsOnce(), 1200)
    return () => clearTimeout(id)
  }, [Boolean(fc)])

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
            place_label: place ? placeLabel(place) : undefined,
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

  const focusPlace = useCallback((p: Place) => {
    setPlace(p)
    setUsingDevice(false)
    save({ place: p })
  }, [])
  const placeControl = useMemo(() => ({ current: place, focus: focusPlace }), [place, focusPlace])

  return (
    <PlaceContext.Provider value={placeControl}>
      <div className={`app ${chatOpen ? 'chat-open' : ''}`}>
        <SkyCanvas target={sky} />

        <main className="stage">
          <header className="topbar">
            <Logo size={42} className="topbar-logo" />
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
            <LiveBell state={liveState} inbox={inbox} unread={unread} onOpen={() => setUnread(0)} onAsk={askAboutAlert} />
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
              <AlertRibbon bundle={alerts} onAsk={() => send(`What weather warnings are active for ${placeLabel(place ?? FALLBACK)} right now, and what should I do?`)} />
              <InsightStrip items={insights} onAsk={(kind) => send((INSIGHT_QUESTIONS[kind] ?? INSIGHT_QUESTIONS.day)(placeLabel(place ?? FALLBACK)))} />
              <TimeDial hours={fc.hourly} selected={hour} onSelect={setHour} />
              <DayStrip days={fc.daily} />
              {place && <RadarMap place={place} />}
            </>
          ) : (
            !loadError && (
              <div className="boot">
                <span className="logo-lockup">
                  <LogoMark size={120} />
                  <Wordmark size={30} />
                </span>
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

        <AlertToasts toasts={toasts} onDismiss={(id) => setToasts((all) => all.filter((t) => t.alert.id !== id))} onAsk={(a) => {
          setToasts((all) => all.filter((t) => t.alert.id !== a.alert.id))
          askAboutAlert(a)
        }} />

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
            current={place && place.name !== 'Locating…' ? place : null}
            onToggleSave={(p) =>
              setProfile((prev) =>
                prev.places.some((x) => Math.abs(x.lat - p.lat) < 0.01 && Math.abs(x.lon - p.lon) < 0.01) ? removePlace(prev, p) : addPlace(prev, p),
              )
            }
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
    </PlaceContext.Provider>
  )
}
