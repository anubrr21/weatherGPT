import { BookOpen, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import type { SourcesData } from '../../lib/types'
import CardShell from './CardShell'

export default function SourcesCard({ data }: { data: SourcesData }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <CardShell title="Official sources" meta={`${data.results.length} passages · IMD / NDMA`}>
      <ol className="sources">
        {data.results.map((r, i) => (
          <li key={`${r.url}-${i}`}>
            <button className="source-head" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}>
              <BookOpen size={14} />
              <span>
                <b>{r.publisher}</b> · {r.title}
                {r.page ? <em> · p.{r.page}</em> : null}
              </span>
            </button>
            {open === i && (
              <div className="source-body">
                <p>{r.text.length > 900 ? `${r.text.slice(0, 900)}…` : r.text}</p>
                <a href={r.url} target="_blank" rel="noreferrer">
                  Open original <ExternalLink size={12} />
                </a>
              </div>
            )}
          </li>
        ))}
      </ol>
    </CardShell>
  )
}
