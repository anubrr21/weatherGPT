import type { ReactNode } from 'react'

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|(?<!\w)__[^_]+__(?!\w)|\*[^*\s][^*]*\*|(?<!\w)_[^_\s].*?_(?!\w)|`[^`]+`)/g
  let last = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyBase}-${i++}`
    if (token.startsWith('**') || token.startsWith('__')) out.push(<strong key={key}>{inline(token.slice(2, -2), key)}</strong>)
    else if (token.startsWith('`')) out.push(<code key={key}>{token.slice(1, -1)}</code>)
    else out.push(<em key={key}>{inline(token.slice(1, -1), key)}</em>)
    last = match.index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export default function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const items = list.items.map((item, i) => <li key={i}>{inline(item, `li-${blocks.length}-${i}`)}</li>)
    blocks.push(list.ordered ? <ol key={`l${blocks.length}`}>{items}</ol> : <ul key={`l${blocks.length}`}>{items}</ul>)
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = line.match(/^\s*(?:[-*•])\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      const ordered = Boolean(numbered)
      if (!list || list.ordered !== ordered) {
        flush()
        list = { ordered, items: [] }
      }
      list.items.push((bullet ?? numbered)![1])
      continue
    }
    flush()
    if (!line.trim()) continue
    const heading = line.match(/^#{1,4}\s+(.*)$/)
    if (heading) blocks.push(<h4 key={`h${blocks.length}`}>{inline(heading[1], `h${blocks.length}`)}</h4>)
    else blocks.push(<p key={`p${blocks.length}`}>{inline(line, `p${blocks.length}`)}</p>)
  }
  flush()
  return <div className="md">{blocks}</div>
}
