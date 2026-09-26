import type { ReactNode } from 'react'

export default function CardShell({ title, meta, tone, children }: { title: string; meta?: string; tone?: string; children: ReactNode }) {
  return (
    <section className={`card ${tone ? `card-${tone}` : ''}`}>
      <header className="card-head">
        <h3>{title}</h3>
        {meta && <span>{meta}</span>}
      </header>
      {children}
    </section>
  )
}
