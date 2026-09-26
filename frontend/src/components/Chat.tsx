import { ArrowUp, ChevronDown, Loader2, Mic, Square, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Health } from '../lib/api'
import { LANGUAGES, PROMPTS, languageByCode } from '../lib/languages'
import type { Message } from '../lib/types'
import { speak, stopSpeaking, useListen } from '../lib/voice'
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

export default function Chat({ messages, busy, language, llm, onLanguage, onSend, onStop, onCollapse }: Props) {
  const [draft, setDraft] = useState('')
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const lang = languageByCode(language)
  const listRef = useRef<HTMLDivElement>(null)
  const voiceTurn = useRef(false)
  const listen = useListen(lang.speech, (text) => {
    voiceTurn.current = true
    onSend(text, true)
  })

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const lastAssistant = messages.length ? messages[messages.length - 1] : undefined
  useEffect(() => {
    if (!lastAssistant || lastAssistant.role !== 'assistant' || lastAssistant.pending || !lastAssistant.text) return
    if (autoSpeak || voiceTurn.current) {
      voiceTurn.current = false
      setSpeakingId(lastAssistant.id)
      speak(lastAssistant.text, lang.speech, () => setSpeakingId(null))
    }
  }, [lastAssistant?.pending])

  const submit = () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    onSend(text, false)
  }

  const prompts = PROMPTS[language] ?? PROMPTS.en

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
                ? `AI · ${llm.providers.map((p) => p.name).join(' → ')} · live data`
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
        {messages.map((m) => (
          <article key={m.id} className={`msg ${m.role}`}>
            {m.role === 'user' ? (
              <p>{m.text}</p>
            ) : (
              <>
                {m.steps.length > 0 && (
                  <ol className="steps">
                    {m.steps.map((s, i) => (
                      <li key={i} className={m.pending && i === m.steps.length - 1 && !m.text ? 'running' : 'done'}>{s}</li>
                    ))}
                  </ol>
                )}
                {m.cards.map((c, i) => (
                  <DataCard key={i} card={c} />
                ))}
                {m.text && <Markdown text={m.text} />}
                {m.pending && !m.text && m.steps.length === 0 && <Loader2 className="spin" size={18} />}
                {m.error && <p className="msg-error">{m.error}</p>}
                {!m.pending && m.provider?.fallback && <p className="msg-provider">Answered by backup: {m.provider.label}</p>}
                {!m.pending && m.text && (
                  <button
                    className="speak-btn"
                    onClick={() => {
                      if (speakingId === m.id) {
                        stopSpeaking()
                        setSpeakingId(null)
                      } else {
                        setSpeakingId(m.id)
                        speak(m.text, lang.speech, () => setSpeakingId(null))
                      }
                    }}
                  >
                    {speakingId === m.id ? <Square size={12} /> : <Volume2 size={13} />} {speakingId === m.id ? 'Stop' : 'Listen'}
                  </button>
                )}
              </>
            )}
          </article>
        ))}
      </div>

      <footer className="composer">
        {listen.error && <p className="voice-error">{listen.error}</p>}
        <div className={`composer-box ${listen.listening ? 'listening' : ''}`}>
          {listen.listening ? (
            <div className="interim" aria-live="polite">
              <span className="wave"><i /><i /><i /><i /><i /></span>
              {listen.interim || `Listening in ${lang.native}…`}
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
            className={`mic ${listen.listening ? 'on' : ''}`}
            onClick={() => (listen.listening ? listen.stop() : listen.start())}
            aria-label={listen.listening ? 'Stop listening' : 'Speak your question'}
            disabled={busy}
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
