import { Check, MessageSquare, Pencil, Pin, PinOff, Search, Share2, SquarePen, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { ago, chatAsText, groupChats, type Conversation } from '../lib/chats'

interface Props {
  open: boolean
  chats: Conversation[]
  activeId: string
  onClose: () => void
  onNew: () => void
  onOpen: (id: string) => void
  onRename: (id: string, title: string) => void
  onPin: (id: string) => void
  onDelete: (id: string) => void
  onClear: () => void
}

export default function ChatHistory({ open, chats, activeId, onClose, onNew, onOpen, onRename, onPin, onDelete, onClear }: Props) {
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [shared, setShared] = useState<string | null>(null)
  const groups = useMemo(() => groupChats(chats, query), [chats, query])

  const commit = () => {
    if (editing && editing.title.trim()) onRename(editing.id, editing.title.trim())
    setEditing(null)
  }

  const share = async (chat: Conversation) => {
    const text = chatAsText(chat)
    try {
      if (navigator.share) await navigator.share({ title: chat.title, text })
      else await navigator.clipboard.writeText(text)
      setShared(chat.id)
      window.setTimeout(() => setShared((id) => (id === chat.id ? null : id)), 1600)
    } catch {
      return
    }
  }

  return (
    <div className={`history ${open ? 'open' : ''}`} aria-hidden={!open}>
      <button className="history-scrim" onClick={onClose} aria-label="Close chat history" tabIndex={open ? 0 : -1} />
      <nav className="history-panel" aria-label="Chat history">
        <div className="history-top">
          <strong>Chats</strong>
          <button className="icon-btn" onClick={onClose} aria-label="Close chat history">
            <X size={18} />
          </button>
        </div>
        <button className="history-new" onClick={onNew}>
          <SquarePen size={16} />
          New chat
        </button>
        <label className="history-search">
          <Search size={15} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search chats" aria-label="Search chats" />
          {query && (
            <button onClick={() => setQuery('')} aria-label="Clear search">
              <X size={14} />
            </button>
          )}
        </label>

        <div className="history-list">
          {groups.length === 0 && (
            <p className="history-empty">
              <MessageSquare size={20} />
              {query ? 'No chats match that search.' : 'Your conversations will appear here.'}
            </p>
          )}
          {groups.map((group) => (
            <section key={group.label}>
              <h3>{group.label}</h3>
              {group.items.map((chat) => {
                const renaming = editing?.id === chat.id
                return (
                  <div key={chat.id} className={`history-row ${chat.id === activeId ? 'active' : ''}`}>
                    {renaming ? (
                      <form
                        className="history-rename"
                        onSubmit={(e) => {
                          e.preventDefault()
                          commit()
                        }}
                      >
                        <input autoFocus value={editing.title} maxLength={80} onChange={(e) => setEditing({ id: chat.id, title: e.target.value })} onBlur={commit} aria-label="Chat title" />
                        <button type="submit" aria-label="Save title">
                          <Check size={15} />
                        </button>
                      </form>
                    ) : (
                      <button className="history-open" onClick={() => onOpen(chat.id)}>
                        <span className="history-title">{chat.title}</span>
                        <span className="history-meta">
                          {[chat.place, `${chat.messages.filter((m) => m.role === 'user').length} asked`, ago(chat.updatedAt)].filter(Boolean).join(' · ')}
                        </span>
                      </button>
                    )}
                    {!renaming && (
                      <div className="history-actions">
                        {confirm === chat.id ? (
                          <>
                            <button
                              className="danger"
                              onClick={() => {
                                onDelete(chat.id)
                                setConfirm(null)
                              }}
                            >
                              Delete
                            </button>
                            <button onClick={() => setConfirm(null)}>Keep</button>
                          </>
                        ) : (
                          <>
                            <button onClick={() => onPin(chat.id)} aria-label={chat.pinned ? 'Unpin chat' : 'Pin chat'} title={chat.pinned ? 'Unpin' : 'Pin'}>
                              {chat.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                            </button>
                            <button onClick={() => setEditing({ id: chat.id, title: chat.title })} aria-label="Rename chat" title="Rename">
                              <Pencil size={14} />
                            </button>
                            <button onClick={() => void share(chat)} aria-label="Share chat" title="Share">
                              {shared === chat.id ? <Check size={14} /> : <Share2 size={14} />}
                            </button>
                            <button onClick={() => setConfirm(chat.id)} aria-label="Delete chat" title="Delete">
                              <Trash2 size={14} />
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </section>
          ))}
        </div>

        <div className="history-foot">
          <span>Saved on this device</span>
          {chats.length > 0 &&
            (confirm === 'all' ? (
              <span className="history-clear">
                <button
                  className="danger"
                  onClick={() => {
                    onClear()
                    setConfirm(null)
                  }}
                >
                  Delete all
                </button>
                <button onClick={() => setConfirm(null)}>Keep</button>
              </span>
            ) : (
              <button onClick={() => setConfirm('all')}>Clear all</button>
            ))}
        </div>
      </nav>
    </div>
  )
}
