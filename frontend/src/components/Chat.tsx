import { ArrowUp, ChevronDown, Loader2, Mic, Square, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Health } from '../lib/api'
import { LANGUAGES, PROMPTS, languageByCode } from '../lib/languages'
import type { Message } from '../lib/types'
import { speak, speakableFromMarkdown, splitSpeak, stopSpeaking, useListen } from '../lib/voice'
import DataCard from './cards'
import Markdown from './Markdown'

interface Props {
  messages: Message[]
  busy: boolean
  language: string
  llm: Health | null
  onLanguage: (code: string) => void
  onSend: (text: string, viaVoice: boolean) => void
  onStop: () => void
  onCollapse?: () => void
}

type Speaking = { id: string; phase: 'loading' | 'playing' } | null

export default function Chat({ messages, busy, language, llm, onLanguage, onSend, onStop, onCollapse }: Props) {
  const [draft, setDraft] = useState('')
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [speaking, setSpeaking] = useState<Speaking>(null)
  const lang = languageByCode(language)
  const listRef = useRef<HTMLDivElement>(null)
  const voiceTurn = useRef(false)
  const spokenFor = useRef<string | null>(null)
  const neural = Boolean(llm?.neural_voice)
  const listen = useListen(lang.code, lang.speech, Boolean(llm?.server_stt), (text) => {
    voiceTurn.current = true
    onSend(text, true)
  })

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const say = (id: string, text: string) => {
    if (!text.trim()) return
    setSpeaking({ id, phase: 'loading' })
    speak(
      text,
      lang.speech,
      lang.code,
      neural,
      () => setSpeaking({ id, phase: 'playing' }),
      () => setSpeaking((s) => (s?.id === id ? null : s)),
    )
  }

  const spokenText = (m: Message) => {
    const { display, spoken } = splitSpeak(m.text, false)
    return spoken || speakableFromMarkdown(display)
  }

  const last = messages.length ? messages[messages.length - 1] : undefined
  useEffect(() => {
    if (!last || last.role !== 'assistant' || spokenFor.current === last.id) return
    if (!autoSpeak && !voiceTurn.current) return
    const { spoken } = splitSpeak(last.text, Boolean(last.pending))
    const ready = spoken ?? (!last.pending && last.text ? spokenText(last) : null)
    if (!ready) return
    spokenFor.current = last.id
    voiceTurn.current = false
    say(last.id, ready)
  }, [last?.text, last?.pending])

  const submit = () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    onSend(text, false)
  }

  const prompts = PROMPTS[language] ?? PROMPTS.en
  const listening = listen.phase === 'listening'

  return (
    <section className="chat">
      <header className="chat-head">
        {onCollapse && (
          <button className="icon-btn" onClick={onCollapse} aria-label="Collapse chat">
            <ChevronDown size={20} />
          </button>
        )}
        <div className="chat-title">
          <span className="brand">Weather<b>GPT</b></span>
          <small>
            {llm === null
              ? 'connecting…'
              : llm.llm
                ? `AI · ${[...new Set(llm.providers.map((p) => p.name))].join(' → ')} · live data`
                : 'offline intent mode'}
          </small>
        </div>
        <label className="lang-select">
          <span className="sr-only">Language</span>
          <select value={language} onChange={(e) => onLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>{l.native}</option>
            ))}
          </select>
        </label>
        <button
          className={`icon-btn ${autoSpeak ? 'active' : ''}`}
          onClick={() => {
            if (autoSpeak) stopSpeaking()
            setAutoSpeak(!autoSpeak)
          }}
          aria-label={autoSpeak ? 'Stop reading replies aloud' : 'Read replies aloud'}
          title={autoSpeak ? 'Auto-speak on' : 'Auto-speak off'}
        >
          {autoSpeak ? <Volume2 size={18} /> : <VolumeX size={18} />}
        </button>
      </header>

      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <div className="empty">
            <h2>Ask the sky anything.</h2>
            <p>Forecasts from GFS, ECMWF &amp; ICON, live IMD warnings, 35 years of climate record — in your language, by voice or text.</p>
            <div className="prompts">
              {prompts.map((p) => (
                <button key={p.text} onClick={() => onSend(p.text, false)}>
                  <span>{p.persona}</span>
                  {p.text}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => {
          if (m.role === 'user') {
            return (
              <article key={m.id} className="msg user">
                <p>{m.text}</p>
              </article>
            )
          }
          const { display } = splitSpeak(m.text, Boolean(m.pending))
          const mine = speaking?.id === m.id ? speaking : null
          return (
            <article key={m.id} className="msg assistant">
              {m.steps.length > 0 && (
                <ol className="steps">
                  {m.steps.map((s, i) => (
                    <li key={i} className={m.pending && i === m.steps.length - 1 && !display ? 'running' : 'done'}>{s}</li>
                  ))}
                </ol>
              )}
              {m.cards.map((c, i) => (
                <DataCard key={i} card={c} />
              ))}
              {display && <Markdown text={display} />}
              {m.pending && !display && m.steps.length === 0 && <Loader2 className="spin" size={18} />}
              {m.error && <p className="msg-error">{m.error}</p>}
              {!m.pending && m.provider?.fallback && <p className="msg-provider">Answered by backup: {m.provider.label}</p>}
              {(!m.pending || mine) && m.text && (
                <button
                  className={`speak-btn ${mine ? 'on' : ''}`}
                  onClick={() => {
                    if (mine) {
                      stopSpeaking()
                      setSpeaking(null)
                    } else {
                      say(m.id, spokenText(m))
                    }
                  }}
                >
                  {mine?.phase === 'loading' ? <Loader2 size={13} className="spin" /> : mine ? <Square size={12} /> : <Volume2 size={13} />}
                  {mine?.phase === 'loading' ? 'Preparing voice…' : mine ? 'Stop' : 'Listen'}
                </button>
              )}
            </article>
          )
        })}
      </div>

      <footer className="composer">
        {listen.error && <p className="voice-error">{listen.error}</p>}
        <div className={`composer-box ${listen.phase !== 'idle' ? 'listening' : ''}`}>
          {listen.phase !== 'idle' ? (
            <div className="interim" aria-live="polite">
              <span className="wave" style={{ ['--level' as string]: listen.phase === 'listening' ? Math.max(listen.level, 0.15) : 0.3 }}>
                <i /><i /><i /><i /><i />
              </span>
              {listen.phase === 'transcribing' ? 'Understanding…' : listen.interim || `Listening in ${lang.native}… (stops when you pause)`}
            </div>
          ) : (
            <textarea
              value={draft}
              rows={1}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  submit()
                }
              }}
              placeholder={language === 'en' ? 'Ask about rain, heat, warnings, crops, sea…' : `${lang.native} · ask by voice or text`}
              aria-label="Message"
            />
          )}
          <button
            className={`mic ${listening ? 'on' : ''}`}
            onClick={() => (listening ? listen.stop() : listen.start())}
            aria-label={listening ? 'Stop listening' : 'Speak your question'}
            disabled={busy || listen.phase === 'transcribing'}
          >
            <Mic size={20} />
          </button>
          {busy ? (
            <button className="send" onClick={onStop} aria-label="Stop">
              <Square size={16} />
            </button>
          ) : (
            <button className="send" onClick={submit} disabled={!draft.trim()} aria-label="Send">
              <ArrowUp size={18} />
            </button>
          )}
        </div>
      </footer>
    </section>
  )
}
