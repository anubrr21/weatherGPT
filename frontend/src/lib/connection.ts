import { Network } from '@capacitor/network'
import { useEffect, useState } from 'react'
import { isNative } from './native'

export type DataMode = 'auto' | 'on' | 'off'

const KEY = 'weathergpt:data-saver'

interface NetworkInformation extends EventTarget {
  saveData?: boolean
  effectiveType?: string
}

export interface Connection {
  online: boolean
  lite: boolean
  reason: string | null
  kind: string
}

export function loadDataMode(): DataMode {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'on' || value === 'off' ? value : 'auto'
  } catch {
    return 'auto'
  }
}

export function saveDataMode(mode: DataMode) {
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    return
  }
}

function info(): NetworkInformation | undefined {
  return (navigator as Navigator & { connection?: NetworkInformation }).connection
}

function slowness(): string | null {
  const net = info()
  if (!net) return null
  if (net.saveData) return 'your phone is in data saver mode'
  if (net.effectiveType === 'slow-2g' || net.effectiveType === '2g') return 'you are on a 2G connection'
  if (net.effectiveType === '3g') return 'you are on a slow 3G connection'
  return null
}

export function useConnection(mode: DataMode): Connection {
  const [online, setOnline] = useState(() => navigator.onLine)
  const [slow, setSlow] = useState<string | null>(slowness)
  const [kind, setKind] = useState(() => info()?.effectiveType ?? 'unknown')

  useEffect(() => {
    const update = () => {
      setOnline(navigator.onLine)
      setSlow(slowness())
      setKind(info()?.effectiveType ?? 'unknown')
    }
    window.addEventListener('online', update)
    window.addEventListener('offline', update)
    const net = info()
    net?.addEventListener('change', update)
    let removeNative: (() => void) | null = null
    if (isNative) {
      Network.getStatus()
        .then((s) => {
          setOnline(s.connected)
          setKind(s.connectionType)
        })
        .catch(() => undefined)
      Network.addListener('networkStatusChange', (s) => {
        setOnline(s.connected)
        setKind(s.connectionType)
        setSlow(slowness())
      })
        .then((handle) => (removeNative = () => handle.remove()))
        .catch(() => undefined)
    }
    return () => {
      window.removeEventListener('online', update)
      window.removeEventListener('offline', update)
      net?.removeEventListener('change', update)
      removeNative?.()
    }
  }, [])

  const lite = mode === 'on' || (mode === 'auto' && slow !== null)
  const reason = mode === 'on' ? 'you turned data saver on' : lite ? slow : null
  return { online, lite, reason, kind }
}
