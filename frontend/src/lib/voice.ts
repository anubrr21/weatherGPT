import { useCallback, useEffect, useRef, useState } from 'react'

interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}

interface RecognitionEvent {
  resultIndex: number
  results: ArrayLike<RecognitionResult>
}

interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: RecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}

type RecognitionCtor = new () => Recognition

const Ctor: RecognitionCtor | undefined =
  (window as unknown as { SpeechRecognition?: RecognitionCtor }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition

export function useListen(lang: string, onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<string | null>(null)
  const recRef = useRef<Recognition | null>(null)
  const finalRef = useRef('')
  const onFinalRef = useRef(onFinal)
  onFinalRef.current = onFinal

  const stop = useCallback(() => recRef.current?.stop(), [])

  const start = useCallback(() => {
    if (!Ctor) {
      setError('Voice input is not supported in this browser. Try Chrome or the Android app.')
      return
    }
    recRef.current?.abort()
    const rec = new Ctor()
    rec.lang = lang
    rec.interimResults = true
    rec.continuous = false
    finalRef.current = ''
    rec.onresult = (e) => {
      let live = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        if (r.isFinal) finalRef.current += r[0].transcript
        else live += r[0].transcript
      }
      setInterim(finalRef.current + live)
    }
    rec.onerror = (e) => {
      if (e.error !== 'aborted' && e.error !== 'no-speech') setError(`Voice error: ${e.error}`)
    }
    rec.onend = () => {
      setListening(false)
      setInterim('')
      const text = finalRef.current.trim()
      if (text) onFinalRef.current(text)
    }
    recRef.current = rec
    setError(null)
    setListening(true)
    rec.start()
  }, [lang])

  useEffect(() => () => recRef.current?.abort(), [])

  return { supported: Boolean(Ctor), listening, interim, error, start, stop }
}

const cleanForSpeech = (text: string) =>
  text
    .replace(/_Offline mode:[^_]*_/g, '')
    .replace(/[*_`#>]/g, '')
    .replace(/\s+-\s+/g, '. ')
    .replace(/°C/g, ' degrees')
    .replace(/km\/h/g, ' kilometres per hour')
    .replace(/\n+/g, '. ')

export function speak(text: string, lang: string, onEnd?: () => void) {
  if (!('speechSynthesis' in window)) return false
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(cleanForSpeech(text))
  utterance.lang = lang
  const voices = window.speechSynthesis.getVoices()
  const base = lang.split('-')[0]
  utterance.voice =
    voices.find((v) => v.lang === lang) ?? voices.find((v) => v.lang.startsWith(base)) ?? null
  utterance.rate = 1
  utterance.onend = () => onEnd?.()
  utterance.onerror = () => onEnd?.()
  window.speechSynthesis.speak(utterance)
  return true
}

export const stopSpeaking = () => window.speechSynthesis?.cancel()
