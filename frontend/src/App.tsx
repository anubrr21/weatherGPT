import { CloudSun, MapPin, MessageSquareText, RefreshCw, Route, Tornado, UserRound, Zap } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AlertRibbon from './components/AlertRibbon'
import Chat from './components/Chat'
import DayStrip from './components/DayStrip'
import Hud from './components/Hud'
import InsightStrip from './components/InsightStrip'
import { AlertToasts, LiveBell, type Toast } from './components/LiveAlerts'
import Logo, { LogoMark, Wordmark } from './components/Logo'
import LocationSearch from './components/LocationSearch'
import NetBanner from './components/NetBanner'
import TripPlanner from './components/trip/TripPlanner'
import CycloneView from './components/cyclones/CycloneView'
import ErrorBoundary from './components/ErrorBoundary'
import LightningView from './components/lightning/LightningView'
import ProfileSheet from './components/ProfileSheet'
import RadarGate from './components/RadarGate'
import SkyCanvas from './components/SkyCanvas'
import TimeDial from './components/TimeDial'
import { api, streamChat, type Health } from './lib/api'
import { placeLabel } from './lib/format'
import { PlaceContext } from './lib/placeContext'
import { addPlace, applyPatch, loadProfile, removePlace, saveProfile } from './lib/profile'
import { syncSubscriptions, useLiveAlerts, type LiveAlert } from './lib/live'
import { initNative, notifyAlert, promptNotificationsOnce, type AlertTap } from './lib/native'
import { loadPrefs, savePrefs, syncPrefs, useNotices, type Notice, type NotifyPrefs } from './lib/notices'
import { loadDataMode, saveDataMode, useConnection, type DataMode } from './lib/connection'
import { offlineAnswer, withCache } from './lib/offline'
import type { TripResult } from './lib/trip'
import { unlockAudio } from './lib/voice'
import { momentAt, skyFor } from './lib/sky'
import type { AlertsBundle, ChatEvent, Forecast, Insight, Message, Place, Profile } from './lib/types'

const FALLBACK: Place = { name: 'Amaravati', district: 'Guntur', state: 'Andhra Pradesh', lat: 16.514, lon: 80.516 }
const STORE = 'weathergpt:v1'

type View = 'weather' | 'trip' | 'cyclones' | 'lightning'

interface Saved {
  place?: Place
  language?: string
  view?: View
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
  const [toasts, setToasts] = useState<Toast[]>([])
  const toastTargets = useRef(new Map<string, () => void>())
  const [bellOpen, setBellOpen] = useState(false)
  const [focusNotice, setFocusNotice] = useState<number | null>(null)
  const [notifyPrefs, setNotifyPrefs] = useState<NotifyPrefs>(loadPrefs)
  const [dataMode, setDataModeState] = useState<DataMode>(loadDataMode)
  const connection = useConnection(dataMode)
  const [staleAt, setStaleAt] = useState<number | null>(null)
  const [view, setViewState] = useState<View>(saved.view ?? 'weather')
  const [tripBrief, setTripBrief] = useState<Record<string, unknown> | null>(null)
  const [incomingTrip, setIncomingTrip] = useState<TripResult | null>(null)
  const setView = (next: View) => {
    setViewState(next)
    save({ view: next })
  }
  const setDataMode = (mode: DataMode) => {
    saveDataMode(mode)
    setDataModeState(mode)
  }
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
    withCache('forecast', place.lat, place.lon, () => api.forecast(place.lat, place.lon), connection.online)
      .then((result) => {
        setFc(result.data)
        setStaleAt(result.cached ? result.savedAt : null)
        setHour(null)
      })
      .catch((e: Error) => setLoadError(connection.online ? e.message : 'You are offline and nothing is saved for this place yet'))
    withCache('alerts', place.lat, place.lon, () => api.alerts(place.lat, place.lon), connection.online)
      .then((result) => setAlerts(result.data))
      .catch(() => setAlerts(null))
  }, [place?.lat, place?.lon, connection.online])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, (connection.lite ? 20 : 10) * 60 * 1000)
    return () => clearInterval(id)
  }, [refresh, connection.lite])

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
    withCache(`insights:${insightKey}`, place.lat, place.lon, () => api.insights(place.lat, place.lon, profile), connection.online)
      .then((result) => setInsights(result.data))
      .catch(() => setInsights(null))
  }, [place?.lat, place?.lon, fc?.current.time, insightKey])

  const pushToast = (toast: Toast, target: () => void) => {
    toastTargets.current.set(toast.id, target)
    setToasts((all) => (all.some((t) => t.id === toast.id) ? all : [toast, ...all]))
  }

  const noticeRef = useRef<(n: Notice) => void>(() => undefined)
  const liveState = useLiveAlerts(
    (incoming) => {
      pushToast(
        { id: `a:${incoming.alert.id}`, severity: incoming.alert.severity, title: `${incoming.alert.event ?? 'Weather alert'} · ${incoming.place.name}`, body: incoming.alert.headline },
        () => askAboutAlert(incoming),
      )
      notifyAlert(incoming)
      if (place && Math.abs(incoming.place.lat - place.lat) < 0.05 && Math.abs(incoming.place.lon - place.lon) < 0.05) {
        api.alerts(place.lat, place.lon).then(setAlerts).catch(() => undefined)
      }
    },
    (notice) => noticeRef.current(notice),
  )
  const noticeFeed = useNotices(liveState)
  noticeRef.current = (notice) => {
    noticeFeed.receive(notice)
    const fresh = Date.now() - new Date(notice.created_at).getTime() < 30 * 60 * 1000
    if (notice.kind !== 'official' && fresh) pushToast({ id: `n:${notice.id}`, severity: notice.severity, title: notice.title, body: notice.body }, () => openNotice(notice.id))
  }

  const openNotice = (id: number) => {
    setBellOpen(true)
    setFocusNotice(null)
    window.setTimeout(() => setFocusNotice(id), 0)
  }

  const goToNotice = async (n: Notice) => {
    setBellOpen(false)
    setUsingDevice(false)
    try {
      const resolved = await api.reverse(n.place.lat, n.place.lon)
      const next = { ...resolved, name: n.place.name || resolved.name }
      setPlace(next)
      save({ place: next })
    } catch {
      setPlace({ name: n.place.name, lat: n.place.lat, lon: n.place.lon })
    }
  }

  const askNotice = (n: Notice) => {
    setBellOpen(false)
    noticeFeed.markRead([n.id])
    const original = typeof n.data.original === 'string' ? n.data.original : null
    send(
      n.kind === 'official' && original
        ? `IMD has issued "${String(n.data.event ?? n.title)}" (${n.severity}) for ${n.place.name}: ${original} What exactly should I do?`
        : `I got this WeatherGPT alert for ${n.place.name}: "${n.title.replace(/^[^\p{L}\p{N}]+/u, '')}. ${n.body}" What should I do, and how sure is it?`,
    )
  }

  const radarNotice = async (n: Notice) => {
    noticeFeed.markRead([n.id])
    await goToNotice(n)
    window.setTimeout(() => document.querySelector('.radar')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 700)
  }

  useEffect(() => {
    savePrefs(notifyPrefs)
    const id = setTimeout(() => syncPrefs(notifyPrefs, language, profile.role, profile.crops).catch(() => undefined), 800)
    return () => clearTimeout(id)
  }, [JSON.stringify(notifyPrefs), language, profile.role, JSON.stringify(profile.crops), liveState === 'live'])

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
    else if (bellOpen) setBellOpen(false)
    else if (profileOpen) setProfileOpen(false)
    else if (chatOpen) setChatOpen(false)
    else return false
    return true
  }
  nativeRef.current.tap = async (tap: AlertTap) => {
    if (tap.noticeId !== null) {
      await noticeFeed.refresh()
      const stub: Notice = {
        id: tap.noticeId, kind: (tap.kind ?? 'official') as Notice['kind'], severity: 'Info', title: '', body: '', place: { name: tap.place, lat: tap.lat, lon: tap.lon },
        data: {}, created_at: new Date().toISOString(), read: false, channel: '',
      }
      const found = noticeFeed.notices.find((n) => n.id === tap.noticeId) ?? stub
      if (tap.action === 'radar') return radarNotice(found)
      if (tap.action === 'ask' && found.title) return askNotice(found)
      await goToNotice(found)
      openNotice(tap.noticeId)
      return
    }
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
    const open = (e: Event) => {
      setIncomingTrip((e as CustomEvent<TripResult>).detail)
      setView('trip')
      if (window.matchMedia('(max-width: 999px)').matches) setChatOpen(false)
    }
    window.addEventListener('weathergpt:open-trip', open)
    return () => window.removeEventListener('weathergpt:open-trip', open)
  }, [])

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
      if (!connection.online) {
        const answer = fc && place ? offlineAnswer(fc, place.name, staleAt ?? Date.now()) : "You're offline and I have nothing saved for this place yet. Connect once and I'll keep a copy for offline use."
        setMessages((all) => [
          ...all,
          { id: uid(), role: 'user', text, cards: [], steps: [] },
          { id: uid(), role: 'assistant', text: answer, cards: [], steps: [] },
        ])
        return
      }
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
            trip: view === 'trip' ? tripBrief : null,
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
    [busy, messages, place, language, profile, connection.online, fc, staleAt, view, tripBrief],
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
        <SkyCanvas target={sky} lite={connection.lite || !connection.online} />

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
            <LiveBell
              state={liveState}
              notices={noticeFeed.notices}
              unread={noticeFeed.unread}
              open={bellOpen}
              focus={focusNotice}
              onOpenChange={setBellOpen}
              onSeen={(ids) => noticeFeed.markRead(ids)}
              onMarkAll={() => noticeFeed.markRead()}
              onAsk={askNotice}
              onRadar={radarNotice}
              onGo={goToNotice}
            />
            <button className={`icon-btn glass ${profile.role !== 'general' ? 'active' : ''}`} onClick={() => setProfileOpen(true)} aria-label="Your profile">
              <UserRound size={17} />
            </button>
          </header>

          <nav className="views" aria-label="Sections">
            <button className={view === 'weather' ? 'on' : ''} onClick={() => setView('weather')} aria-pressed={view === 'weather'}>
              <CloudSun size={15} /> Weather
            </button>
            <button className={view === 'trip' ? 'on' : ''} onClick={() => setView('trip')} aria-pressed={view === 'trip'}>
              <Route size={15} /> Trip planner
            </button>
            <button className={view === 'cyclones' ? 'on' : ''} onClick={() => setView('cyclones')} aria-pressed={view === 'cyclones'}>
              <Tornado size={15} /> Cyclones
            </button>
            <button className={view === 'lightning' ? 'on' : ''} onClick={() => setView('lightning')} aria-pressed={view === 'lightning'}>
              <Zap size={15} /> Lightning
            </button>
          </nav>

          <NetBanner connection={connection} staleAt={staleAt} onRetry={refresh} onLiteOff={() => setDataMode('off')} />

          {view === 'lightning' ? (
            <ErrorBoundary label="The lightning view">
              <LightningView place={place && place.name !== 'Locating…' ? place : null} online={connection.online} language={language} onAsk={(text) => send(text)} />
            </ErrorBoundary>
          ) : view === 'cyclones' ? (
            <ErrorBoundary label="The cyclone view">
              <CycloneView place={place && place.name !== 'Locating…' ? place : null} online={connection.online} onAsk={(text) => send(text)} />
            </ErrorBoundary>
          ) : view === 'trip' ? (
            <TripPlanner
              current={place && place.name !== 'Locating…' ? place : null}
              online={connection.online}
              lite={connection.lite}
              incoming={incomingTrip}
              onTrip={setTripBrief}
              onAsk={(text) => send(text)}
            />
          ) : (
            <>
              {loadError && (
                <div className="ribbon severe">
                  <span>Could not load forecast: {loadError}. Is the backend running on port 8000?</span>
                </div>
              )}

              {fc && moment ? (
                <>
                  <Hud fc={fc} m={moment} savedAt={staleAt} />
                  <AlertRibbon bundle={alerts} onAsk={() => send(`What weather warnings are active for ${placeLabel(place ?? FALLBACK)} right now, and what should I do?`)} />
                  <InsightStrip items={insights} onAsk={(kind) => send((INSIGHT_QUESTIONS[kind] ?? INSIGHT_QUESTIONS.day)(placeLabel(place ?? FALLBACK)))} />
                  <TimeDial hours={fc.hourly} selected={hour} onSelect={setHour} />
                  <DayStrip days={fc.daily} />
                  {place && <RadarGate place={place} lite={connection.lite} online={connection.online} />}
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
            </>
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

        <AlertToasts
          toasts={bellOpen ? [] : toasts}
          onDismiss={(id) => setToasts((all) => all.filter((t) => t.id !== id))}
          onOpen={(id) => {
            setToasts((all) => all.filter((t) => t.id !== id))
            toastTargets.current.get(id)?.()
          }}
        />

        {profileOpen && (
          <ProfileSheet
            profile={profile}
            current={place}
            onChange={setProfile}
            prefs={notifyPrefs}
            onPrefsChange={setNotifyPrefs}
            dataMode={dataMode}
            liteReason={connection.reason}
            onDataMode={setDataMode}
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
