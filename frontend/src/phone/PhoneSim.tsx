import { useCallback, useEffect, useRef, useState } from 'react'
import { phoneApi, type IvrStep, type PhoneMessage, type PhoneStatus, type PhoneThread } from '../lib/phone'
import './phone.css'

type Screen = 'home' | 'messages' | 'call' | 'incoming'

const NUMBER_KEY = 'weathergpt:sim-phone'
const SEEN_KEY = 'weathergpt:sim-seen'
const KEYS: [string, string][] = [
  ['1', '.,?'], ['2', 'abc'], ['3', 'def'], ['4', 'ghi'], ['5', 'jkl'], ['6', 'mno'], ['7', 'pqrs'], ['8', 'tuv'], ['9', 'wxyz'], ['*', '+'], ['0', '␣'], ['#', '⇧'],
]
const TONES: Record<string, [number, number]> = {
  '1': [697, 1209], '2': [697, 1336], '3': [697, 1477], '4': [770, 1209], '5': [770, 1336], '6': [770, 1477],
  '7': [852, 1209], '8': [852, 1336], '9': [852, 1477], '*': [941, 1209], '0': [941, 1336], '#': [941, 1477],
}

function stored(key: string) {
  try {
    return localStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    return
  }
}

let context: AudioContext | null = null

function tone(frequencies: number[], ms: number, gain = 0.08) {
  try {
    context ??= new AudioContext()
    const out = context.createGain()
    out.gain.value = gain
    out.connect(context.destination)
    const end = context.currentTime + ms / 1000
    for (const f of frequencies) {
      const osc = context.createOscillator()
      osc.frequency.value = f
      osc.connect(out)
      osc.start()
      osc.stop(end)
    }
  } catch {
    return
  }
}

const clock = () => new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
const duration = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

export default function PhoneSim() {
  const [number, setNumber] = useState(stored(NUMBER_KEY))
  const [draftNumber, setDraftNumber] = useState(stored(NUMBER_KEY))
  const [thread, setThread] = useState<PhoneThread | null>(null)
  const [status, setStatus] = useState<PhoneStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [screen, setScreen] = useState<Screen>('home')
  const [compose, setCompose] = useState('')
  const [sending, setSending] = useState(false)
  const [step, setStep] = useState<IvrStep | null>(null)
  const [dialled, setDialled] = useState('')
  const [waiting, setWaiting] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [ringing, setRinging] = useState<PhoneMessage | null>(null)
  const [unread, setUnread] = useState(0)
  const [now, setNow] = useState(clock())
  const [drill, setDrill] = useState<string | null>(null)

  const audio = useRef<HTMLAudioElement | null>(null)
  const silence = useRef<number | null>(null)
  const callRef = useRef<{ id: string | null; live: boolean }>({ id: null, live: false })
  const buffer = useRef('')
  const lastSeen = useRef(Number(stored(SEEN_KEY)) || 0)
  const threadEnd = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const t = window.setInterval(() => setNow(clock()), 15000)
    phoneApi.status().then(setStatus).catch(() => undefined)
    return () => window.clearInterval(t)
  }, [])

  const refresh = useCallback(async () => {
    if (!number) return
    try {
      const next = await phoneApi.thread(number)
      setError(null)
      setThread(next)
      const fresh = next.messages.filter((m) => m.direction === 'out' && m.id > lastSeen.current)
      if (fresh.length) {
        const newest = Math.max(...fresh.map((m) => m.id))
        lastSeen.current = newest
        store(SEEN_KEY, String(newest))
        const call = fresh.filter((m) => m.channel === 'voice' && m.status === 'ringing').pop()
        if (call && !callRef.current.live) {
          setRinging(call)
          setScreen('incoming')
        }
        const texts = fresh.filter((m) => m.channel === 'sms').length
        if (texts) {
          setUnread((u) => u + texts)
          tone([1318, 1568], 120, 0.05)
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach WeatherGPT')
    }
  }, [number])

  useEffect(() => {
    if (!number) return
    const first = window.setTimeout(refresh, 0)
    const t = window.setInterval(refresh, 4000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(t)
    }
  }, [number, refresh])

  useEffect(() => {
    if (screen === 'messages') {
      threadEnd.current?.scrollIntoView({ block: 'end' })
      const t = window.setTimeout(() => setUnread(0), 0)
      return () => window.clearTimeout(t)
    }
  }, [screen, thread])

  useEffect(() => {
    if (screen !== 'incoming') return
    tone([440, 480], 900, 0.05)
    const t = window.setInterval(() => tone([440, 480], 900, 0.05), 3000)
    return () => window.clearInterval(t)
  }, [screen])

  useEffect(() => {
    if (screen !== 'call') return
    const t = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [screen])

  const stopAudio = () => {
    if (silence.current) window.clearTimeout(silence.current)
    silence.current = null
    audio.current?.pause()
    audio.current = null
  }

  const hangUp = useCallback(() => {
    stopAudio()
    callRef.current = { id: null, live: false }
    buffer.current = ''
    setStep(null)
    setDialled('')
    setWaiting(false)
    setScreen('home')
    tone([480, 620], 250, 0.05)
    window.setTimeout(refresh, 400)
  }, [refresh])

  const play = useCallback((next: IvrStep) => {
    stopAudio()
    const player = new Audio(phoneApi.audioUrl(next.audio_url))
    audio.current = player
    const afterPrompt = () => {
      if (!callRef.current.live || audio.current !== player) return
      if (next.hangup) {
        hangUp()
        return
      }
      silence.current = window.setTimeout(() => respond(null), next.timeout * 1000)
    }
    player.onended = afterPrompt
    player.onerror = () => window.setTimeout(afterPrompt, 2500)
    player.play().catch(() => window.setTimeout(afterPrompt, 2500))
  }, [hangUp])

  const respond = useCallback(async (digits: string | null, extra: { reason?: string; message_id?: number } = {}) => {
    if (!number) return
    stopAudio()
    setWaiting(true)
    try {
      const next = await phoneApi.call(number, callRef.current.id, digits, extra)
      if (!callRef.current.live) return
      callRef.current.id = next.call_id
      buffer.current = ''
      setDialled('')
      setStep(next)
      play(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Call dropped')
      hangUp()
    } finally {
      setWaiting(false)
    }
  }, [number, play, hangUp])

  const dial = (extra: { reason?: string; message_id?: number } = {}) => {
    if (!number) return
    callRef.current = { id: null, live: true }
    setRinging(null)
    setSeconds(0)
    setStep(null)
    setScreen('call')
    respond(null, extra)
  }

  const press = (key: string) => {
    if (TONES[key]) tone(TONES[key], 140)
    if (screen === 'call' && step?.gather) {
      stopAudio()
      if (key === '#') {
        if (buffer.current) respond(buffer.current)
        return
      }
      buffer.current += key
      setDialled(buffer.current)
      if (buffer.current.length >= step.gather) respond(buffer.current)
      return
    }
    if (screen === 'messages') setCompose((c) => (c + (key === '0' ? ' ' : key)).slice(0, 480))
  }

  const send = async () => {
    const text = compose.trim()
    if (!text || !number) return
    setSending(true)
    setCompose('')
    try {
      await phoneApi.sms(number, text)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Message not sent')
      setCompose(text)
    } finally {
      setSending(false)
    }
  }

  const green = () => {
    if (screen === 'incoming' && ringing) dial({ reason: 'warning', message_id: ringing.id })
    else if (screen === 'messages') send()
    else if (screen !== 'call') dial()
  }

  const red = () => {
    if (screen === 'call') hangUp()
    else {
      setRinging(null)
      setScreen('home')
    }
  }

  const soft = (side: 'left' | 'right') => {
    if (screen === 'home') side === 'left' ? setScreen('messages') : dial()
    else if (screen === 'messages') side === 'left' ? send() : setScreen('home')
    else if (screen === 'incoming') side === 'left' ? green() : red()
    else if (screen === 'call' && side === 'right') hangUp()
  }

  const saveNumber = () => {
    const digits = draftNumber.replace(/\D/g, '').replace(/^(91|0)(?=\d{10}$)/, '')
    if (!/^[6-9]\d{9}$/.test(digits)) {
      setError('Enter a 10 digit Indian mobile number')
      return
    }
    store(NUMBER_KEY, digits)
    store(SEEN_KEY, '0')
    lastSeen.current = Number.MAX_SAFE_INTEGER
    setNumber(digits)
    setDraftNumber(digits)
    setThread(null)
    setError(null)
    phoneApi.thread(digits).then((t) => {
      lastSeen.current = Math.max(0, ...t.messages.map((m) => m.id))
      store(SEEN_KEY, String(lastSeen.current))
      setThread(t)
    }).catch(() => undefined)
  }

  const sendDrill = async () => {
    if (!number) return
    setDrill('Sending…')
    try {
      const result = await phoneApi.drill(number)
      setDrill(result.call ? 'Practice SMS sent. The phone will ring in a moment.' : 'Practice SMS sent. Voice calls are off for this number.')
      refresh()
    } catch (e) {
      setDrill(e instanceof Error ? e.message : 'Could not send')
    }
  }

  const softLabels: Record<Screen, [string, string]> = {
    home: ['Messages', 'Call'],
    messages: [sending ? '…' : 'Send', 'Back'],
    call: ['', 'End'],
    incoming: ['Answer', 'Reject'],
  }
  const sub = thread?.subscriber

  return (
    <div className="sim-page">
      <div className="sim-wrap">
        <div className="handset" aria-label="Keypad phone">
          <div className="earpiece" />
          <div className="lcd">
            <div className="lcd-status">
              <span className="bars" aria-hidden="true"><i /><i /><i /><i /></span>
              <span>{number ? 'Jio 4G' : 'No SIM'}</span>
              <span>{now}</span>
            </div>

            {screen === 'home' && (
              <div className="lcd-home">
                <div className="lcd-clock">{now}</div>
                <div className="lcd-date">{new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</div>
                {unread > 0 && <div className="lcd-badge">✉ {unread} new message{unread > 1 ? 's' : ''}</div>}
                {!number && <div className="lcd-note">Put in a SIM number on the right</div>}
              </div>
            )}

            {screen === 'messages' && (
              <div className="lcd-thread">
                <div className="lcd-title">WeatherGPT</div>
                <div className="bubbles">
                  {(thread?.messages ?? []).filter((m) => m.channel === 'sms').map((m) => (
                    <div key={m.id} className={`bubble ${m.direction}`}>
                      <p>{m.text}</p>
                      <small>
                        {new Date(m.created_at + (m.created_at.endsWith('Z') || m.created_at.includes('+') ? '' : 'Z')).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })}
                        {m.direction === 'out' && ` · ${m.segments} SMS`}
                      </small>
                    </div>
                  ))}
                  {thread && thread.messages.filter((m) => m.channel === 'sms').length === 0 && <p className="lcd-note">Try: WEATHER 522237</p>}
                  <div ref={threadEnd} />
                </div>
                <textarea
                  className="lcd-compose"
                  value={compose}
                  onChange={(e) => setCompose(e.target.value.slice(0, 480))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      send()
                    }
                  }}
                  placeholder="Write message"
                  rows={2}
                  aria-label="Message"
                />
              </div>
            )}

            {screen === 'call' && (
              <div className="lcd-call">
                <div className="lcd-title">WeatherGPT helpline</div>
                <div className="lcd-timer">{waiting && !step ? 'Calling…' : duration(seconds)}</div>
                <p className="lcd-prompt" lang={step?.language ?? undefined}>{waiting ? '…' : step?.text}</p>
                {step?.gather && step.gather > 1 && <div className="lcd-digits">{dialled.padEnd(step.gather, '_')}</div>}
              </div>
            )}

            {screen === 'incoming' && (
              <div className="lcd-incoming">
                <div className="ring">☎</div>
                <div className="lcd-title">WeatherGPT</div>
                <p>{ringing?.data?.drill ? 'Practice warning call' : 'Weather warning call'}</p>
              </div>
            )}

            <div className="lcd-soft">
              <span>{softLabels[screen][0]}</span>
              <span>{softLabels[screen][1]}</span>
            </div>
          </div>

          <div className="nav-row">
            <button className="soft" onClick={() => soft('left')} aria-label={softLabels[screen][0] || 'Left soft key'} />
            <button className="dpad" onClick={() => setScreen(screen === 'home' ? 'messages' : screen)} aria-label="Select" />
            <button className="soft" onClick={() => soft('right')} aria-label={softLabels[screen][1] || 'Right soft key'} />
          </div>
          <div className="call-row">
            <button className="call-key green" onClick={green} aria-label="Call">✆</button>
            <button className="call-key red" onClick={red} aria-label="End"><span>✆</span></button>
          </div>
          <div className="keypad">
            {KEYS.map(([k, letters]) => (
              <button key={k} onClick={() => press(k)} aria-label={k}>
                <b>{k}</b>
                <small>{letters}</small>
              </button>
            ))}
          </div>
        </div>

        <aside className="sim-side">
          <h1>Keypad phone simulator</h1>
          <p>
            This is how WeatherGPT reaches people without a smartphone or internet: plain SMS in their language, a voice helpline
            they can call and use with number keys, and automatic voice calls when an official warning is severe.
          </p>
          <label className="sim-number">
            <span>SIM number</span>
            <input value={draftNumber} inputMode="tel" onChange={(e) => setDraftNumber(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && saveNumber()} placeholder="10 digit mobile" />
            <button onClick={saveNumber}>Insert SIM</button>
          </label>
          {error && <p className="sim-error">{error}</p>}
          {sub && (
            <p className="sim-sub">
              {sub.active && sub.confirmed ? 'Joined warnings' : sub.active ? 'Waiting for YES' : 'Stopped'} · {sub.place ?? 'no place'}
              {sub.district ? `, ${sub.district}` : ''} · {sub.language.toUpperCase()}
            </p>
          )}
          <h2>SMS commands</h2>
          <ul>
            <li><code>WEATHER 522237</code> today's forecast for a PIN code or village</li>
            <li><code>JOIN Tenali</code> warnings and a 6:30 am briefing for a place</li>
            <li><code>LANG TE</code> switch language, or send the language name</li>
            <li><code>STOP</code> end all messages, <code>HELP</code> for this list</li>
            <li>Any question, like <code>kal baarish hogi?</code>, is answered by WeatherGPT</li>
          </ul>
          <h2>Voice helpline</h2>
          <p>Press the green key. Choose a language, type your PIN code, then 1 weather, 2 warnings, 3 farm advice, 4 join, 5 change place, 9 language.</p>
          <button className="sim-drill" disabled={!sub?.active} onClick={sendDrill}>Send a practice warning</button>
          {drill && <p className="sim-sub">{drill}</p>}
          {status?.note && <p className="sim-foot">{status.note}</p>}
        </aside>
      </div>
    </div>
  )
}
