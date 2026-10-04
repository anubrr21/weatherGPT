import { ArrowDown, ArrowUp, Check, ChevronDown, Copy, Loader2, Mic, PanelLeft, Pencil, RefreshCw, Square, SquarePen, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Health } from '../lib/api'
import type { Conversation } from '../lib/chats'
import { LANGUAGES, PROMPTS, languageByCode } from '../lib/languages'
import type { Message } from '../lib/types'
import { speak, speakableFromMarkdown, splitSpeak, stopSpeaking, useListen } from '../lib/voice'
import DataCard from './cards'
import ChatHistory from './ChatHistory'
import Logo from './Logo'
import Markdown from './Markdown'
import './chat.css'

interface Props {
  messages: Message[]
  busy: boolean
  language: string
  llm: Health | null
  onLanguage: (code: string) => void
  onSend: (text: string, viaVoice: boolean) => void
  onStop: () => void
  onCollapse?: () => void
  chats: Conversation[]
  chatId: string
  onNewChat: () => void
  onOpenChat: (id: string) => void
  onRenameChat: (id: string, title: string) => void
  onPinChat: (id: string) => void
  onDeleteChat: (id: string) => void
  onClearChats: () => void
  onRegenerate: () => void
  onEdit: (id: string, text: string) => void
}

type Speaking = { id: string; phase: 'loading' | 'playing' } | null

export default function Chat({
  messages,
  busy,
  language,
  llm,
  onLanguage,
  onSend,
  onStop,
  onCollapse,
  chats,
  chatId,
  onNewChat,
  onOpenChat,
  onRenameChat,
  onPinChat,
  onDeleteChat,
  onClearChats,
  onRegenerate,
  onEdit,
}: Props) {
  const [draft, setDraft] = useState('')
  const [autoSpeak, setAutoSpeak] = useState(false)
  const [speaking, setSpeaking] = useState<Speaking>(null)
  const [voiceError, setVoiceError] = useState<{ id: string; text: string } | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null)
  const [away, setAway] = useState(false)
  const pinnedToEnd = useRef(true)
  const title = chats.find((c) => c.id === chatId)?.title ?? 'New chat'
  const lang = languageByCode(language)
  const listRef = useRef<HTMLDivElement>(null)
  const voiceTurn = useRef(false)
  const spokenFor = useRef<string | null>(null)
  const neural = Boolean(llm?.neural_voice)
  const listen = useListen(lang.code, lang.speech, Boolean(llm?.server_stt), (text) => {
    voiceTurn.current = true
    onSend(text, true)
  })

  const toEnd = (behavior: ScrollBehavior) => listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior })

  useEffect(() => {
    if (pinnedToEnd.current) toEnd('smooth')
  }, [messages])

  useEffect(() => {
    pinnedToEnd.current = true
    setAway(false)
    setEditing(null)
    stopSpeaking()
    setSpeaking(null)
    toEnd('auto')
  }, [chatId])

  const onScroll = () => {
    const list = listRef.current
    if (!list) return
    const gap = list.scrollHeight - list.scrollTop - list.clientHeight
    pinnedToEnd.current = gap < 80
    setAway(gap > 320)
  }

  const copy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(id)
      window.setTimeout(() => setCopied((c) => (c === id ? null : c)), 1500)
    } catch {
      return
    }
  }

  const saveEdit = () => {
    if (!editing || !editing.text.trim() || busy) return
    pinnedToEnd.current = true
    onEdit(editing.id, editing.text.trim())
    setEditing(null)
  }

  const say = (id: string, text: string) => {
    if (!text.trim()) return
    setSpeaking({ id, phase: 'loading' })
    setVoiceError(null)
    speak(text, lang.speech, lang.code, neural, {
      onStart: () => setSpeaking({ id, phase: 'playing' }),
      onEnd: () => setSpeaking((s) => (s?.id === id ? null : s)),
      onError: (message) => {
        setSpeaking((s) => (s?.id === id ? null : s))
        setVoiceError({ id, text: message })
      },
    })
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
    pinnedToEnd.current = true
    onSend(text, false)
  }

  const prompts = PROMPTS[language] ?? PROMPTS.en
  const listening = listen.phase === 'listening'

  return (
    <section className="chat">
      <header className="chat-head">
        <div className="chat-head-row">
          {onCollapse && (
            <button className="icon-btn" onClick={onCollapse} aria-label="Collapse chat">
              <ChevronDown size={20} />
            </button>
          )}
          <button className="icon-btn" onClick={() => setHistoryOpen(true)} aria-label="Chat history" title="Chat history">
            <PanelLeft size={19} />
          </button>
          <Logo size={40} className="chat-logo" />
          <button className="icon-btn" onClick={onNewChat} disabled={messages.length === 0} aria-label="New chat" title="New chat">
            <SquarePen size={18} />
          </button>
          <button
            className={`icon-btn chat-speak ${autoSpeak ? 'active' : ''}`}
            onClick={() => {
              if (autoSpeak) stopSpeaking()
              setAutoSpeak(!autoSpeak)
            }}
            aria-label={autoSpeak ? 'Stop reading replies aloud' : 'Read replies aloud'}
            title={autoSpeak ? 'Auto-speak on' : 'Auto-speak off'}
          >
            {autoSpeak ? <Volume2 size={18} /> : <VolumeX size={18} />}
          </button>
        </div>
        <div className="chat-head-row sub">
          <button className="chat-current" onClick={() => setHistoryOpen(true)} title="Chat history">
            <span key={title}>{title}</span>
          </button>
          <label className="lang-select">
            <span className="sr-only">Language</span>
            <select value={language} onChange={(e) => onLanguage(e.target.value)}>
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.native}</option>
              ))}
            </select>
          </label>
        </div>
      </header>

      <div className="chat-list" ref={listRef} onScroll={onScroll}>
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
            if (editing?.id === m.id) {
              return (
                <article key={m.id} className="msg user editing">
                  <textarea
                    autoFocus
                    value={editing.text}
                    onChange={(e) => setEditing({ id: m.id, text: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        saveEdit()
                      }
                      if (e.key === 'Escape') setEditing(null)
                    }}
                    aria-label="Edit your message"
                  />
                  <div className="msg-edit-actions">
                    <button onClick={() => setEditing(null)}>Cancel</button>
                    <button className="primary" onClick={saveEdit} disabled={!editing.text.trim() || busy}>
                      Send
                    </button>
                  </div>
                </article>
              )
            }
            return (
              <article key={m.id} className="msg user">
                <p>{m.text}</p>
                <div className="msg-tools">
                  <button onClick={() => void copy(m.id, m.text)} aria-label="Copy message" title="Copy">
                    {copied === m.id ? <Check size={13} /> : <Copy size={13} />}
                  </button>
                  <button onClick={() => setEditing({ id: m.id, text: m.text })} disabled={busy} aria-label="Edit message" title="Edit and ask again">
                    <Pencil size={13} />
                  </button>
                </div>
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
              <div className="msg-actions">
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
              {!m.pending && display && (
                <button className="speak-btn" onClick={() => void copy(m.id, display)}>
                  {copied === m.id ? <Check size={13} /> : <Copy size={13} />}
                  {copied === m.id ? 'Copied' : 'Copy'}
                </button>
              )}
              {!m.pending && !busy && m.id === last?.id && (
                <button className="speak-btn" onClick={onRegenerate}>
                  <RefreshCw size={13} />
                  Try again
                </button>
              )}
              </div>
              {voiceError?.id === m.id && <p className="voice-error inline">{voiceError.text}</p>}
            </article>
          )
        })}
      </div>

      {away && (
        <button
          className="chat-to-end"
          onClick={() => {
            pinnedToEnd.current = true
            toEnd('smooth')
          }}
          aria-label="Jump to latest message"
        >
          <ArrowDown size={16} />
        </button>
      )}

      <ChatHistory
        open={historyOpen}
        chats={chats}
        activeId={chatId}
        onClose={() => setHistoryOpen(false)}
        onNew={() => {
          onNewChat()
          setHistoryOpen(false)
        }}
        onOpen={(id) => {
          onOpenChat(id)
          setHistoryOpen(false)
        }}
        onRename={onRenameChat}
        onPin={onPinChat}
        onDelete={onDeleteChat}
        onClear={onClearChats}
      />

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
