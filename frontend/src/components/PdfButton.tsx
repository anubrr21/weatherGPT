import { Check, FileDown, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { downloadFile } from '../lib/download'

interface Props {
  url: string
  name: string
  label?: string
  className?: string
}

export default function PdfButton({ url, name, label = 'Download PDF', className = 'add-btn' }: Props) {
  const [state, setState] = useState<'idle' | 'busy' | 'done'>('idle')
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setState('busy')
    setError(null)
    try {
      await downloadFile(url, name)
      setState('done')
      window.setTimeout(() => setState('idle'), 2500)
    } catch (e) {
      const message = (e as Error).message
      setError(/cancel/i.test(message) ? null : message)
      setState('idle')
    }
  }

  return (
    <>
      <button className={className} onClick={run} disabled={state === 'busy'}>
        {state === 'busy' ? <Loader2 size={14} className="spin" /> : state === 'done' ? <Check size={14} /> : <FileDown size={14} />}
        {state === 'busy' ? 'Preparing the report…' : state === 'done' ? 'Report ready' : label}
      </button>
      {error && <small className="pdf-error">{error}</small>}
    </>
  )
}
