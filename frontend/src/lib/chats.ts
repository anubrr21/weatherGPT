import type { Message } from './types'

const KEY = 'weathergpt:chats:v1'
const MAX_CHATS = 60
const TITLE_LENGTH = 52
const DAY = 86400000
export const RESUME_MS = 3600000

export interface Conversation {
  id: string
  title: string
  renamed?: boolean
  namedFor?: string
  pinned?: boolean
  place?: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export interface ChatGroup {
  label: string
  items: Conversation[]
}

export const newChatId = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`

export function loadChats(): Conversation[] {
  try {
    const list = JSON.parse(localStorage.getItem(KEY) ?? '[]') as Conversation[]
    return Array.isArray(list) ? list.filter((c) => c && c.id && Array.isArray(c.messages)) : []
  } catch {
    return []
  }
}

export function storeChats(list: Conversation[]) {
  const light = (keepCards: number) => list.map((c, i) => (i < keepCards ? c : { ...c, messages: c.messages.map((m) => ({ ...m, cards: [] })) }))
  const attempts = [list, light(8), light(2), light(2).slice(0, 30), light(0).slice(0, 12)]
  for (const attempt of attempts) {
    try {
      localStorage.setItem(KEY, JSON.stringify(attempt))
      return
    } catch {
      continue
    }
  }
}

export function titleFor(messages: Message[]) {
  const first = messages.find((m) => m.role === 'user' && m.text.trim())
  if (!first) return 'New chat'
  const text = first.text.replace(/\s+/g, ' ').trim()
  return text.length > TITLE_LENGTH ? `${text.slice(0, TITLE_LENGTH - 1).trimEnd()}…` : text
}

export const firstAsk = (messages: Message[]) => messages.find((m) => m.role === 'user' && m.text.trim())

const settled = (messages: Message[]): Message[] => messages.map(({ pending: _pending, ...rest }) => rest)

function same(a: Message[], b: Message[]) {
  if (a.length !== b.length) return false
  const x = a[a.length - 1]
  const y = b[b.length - 1]
  return x?.id === y?.id && x?.text === y?.text && x?.error === y?.error && x?.cards.length === y?.cards.length
}

export function upsertChat(list: Conversation[], id: string, messages: Message[], place?: string): Conversation[] {
  const existing = list.find((c) => c.id === id)
  const clean = settled(messages)
  if (existing && same(existing.messages, clean)) return list
  const now = Date.now()
  const next: Conversation = existing
    ? { ...existing, messages: clean, updatedAt: now, title: existing.renamed || existing.namedFor === firstAsk(clean)?.id ? existing.title : titleFor(clean), place: existing.place ?? place }
    : { id, title: titleFor(clean), place, createdAt: now, updatedAt: now, messages: clean }
  const rest = list.filter((c) => c.id !== id)
  const all = [next, ...rest]
  if (all.length <= MAX_CHATS) return all
  const pinned = all.filter((c) => c.pinned)
  const loose = all.filter((c) => !c.pinned).slice(0, Math.max(1, MAX_CHATS - pinned.length))
  return all.filter((c) => pinned.includes(c) || loose.includes(c))
}

export function groupChats(list: Conversation[], query: string): ChatGroup[] {
  const needle = query.trim().toLowerCase()
  const matches = needle
    ? list.filter((c) => c.title.toLowerCase().includes(needle) || (c.place ?? '').toLowerCase().includes(needle) || c.messages.some((m) => m.text.toLowerCase().includes(needle)))
    : list
  const midnight = new Date().setHours(0, 0, 0, 0)
  const buckets: [string, (c: Conversation) => boolean][] = [
    ['Pinned', (c) => Boolean(c.pinned)],
    ['Today', (c) => c.updatedAt >= midnight],
    ['Yesterday', (c) => c.updatedAt >= midnight - DAY],
    ['Last 7 days', (c) => c.updatedAt >= midnight - 7 * DAY],
    ['Last 30 days', (c) => c.updatedAt >= midnight - 30 * DAY],
    ['Older', () => true],
  ]
  const groups: ChatGroup[] = buckets.map(([label]) => ({ label, items: [] }))
  for (const chat of [...matches].sort((a, b) => b.updatedAt - a.updatedAt)) {
    groups[buckets.findIndex(([, test]) => test(chat))].items.push(chat)
  }
  return groups.filter((g) => g.items.length)
}

export function needsName(chat: Conversation | undefined) {
  if (!chat || chat.renamed) return null
  const ask = firstAsk(chat.messages)
  if (!ask || chat.namedFor === ask.id) return null
  const reply = chat.messages[chat.messages.indexOf(ask) + 1]
  if (!reply || reply.role !== 'assistant' || !reply.text.trim() || reply.error) return null
  return { ask, reply }
}

export function chatAsText(chat: Conversation) {
  const lines = chat.messages
    .filter((m) => m.text.trim())
    .map((m) => `${m.role === 'user' ? 'You' : 'WeatherGPT'}: ${m.text.replace(/<speak>[\s\S]*?<\/speak>/g, '').trim()}`)
  return [chat.title, chat.place ? `Place: ${chat.place}` : '', '', ...lines].filter((line, i) => i !== 1 || line).join('\n\n')
}

export function ago(stamp: number) {
  const minutes = Math.round((Date.now() - stamp) / 60000)
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h`
  const days = Math.round(hours / 24)
  return days < 30 ? `${days} d` : new Date(stamp).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
}
