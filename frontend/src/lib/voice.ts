import { useCallback, useEffect, useRef, useState } from 'react'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export function splitSpeak(text: string, streaming: boolean) {
  const open = text.indexOf('<speak>')
  const close = text.indexOf('</speak>')
  if (open === -1) {
    const partial = streaming ? text.match(/<\/?s?p?e?a?k?$/) : null
    return { display: partial ? text.slice(0, partial.index) : text, spoken: null as string | null }
  }
  if (close === -1) {
    return { display: text.slice(0, open).trim(), spoken: null }
  }
  return {
    display: (text.slice(0, open) + text.slice(close + 8)).trim(),
    spoken: text.slice(open + 7, close).trim(),
  }
}

const UNIT_WORDS: [RegExp, string][] = [
  [/(-?\d+(?:\.\d+)?)\s*°\s*C/g, '$1 degrees'],
  [/(\d+(?:\.\d+)?)\s*km\/h/g, '$1 kilometres an hour'],
  [/(\d+(?:\.\d+)?)\s*mm/g, '$1 millimetres'],
  [/(\d+(?:\.\d+)?)\s*%/g, '$1 percent'],
  [/(\d+(?:\.\d+)?)\s*hPa/g, '$1 hectopascals'],
  [/(\d+(?:\.\d+)?)\s*µg\/m³/g, '$1 micrograms'],
  [/(\d+)\s*kt\b/g, '$1 knots'],
]

export function speakableFromMarkdown(markdown: string) {
  let text = markdown
    .replace(/_Offline mode:[^_]*_/g, '')
    .replace(/_AI models were unreachable[^_]*_/g, '')
    .replace(/`[^`]*`/g, '')
    .replace(/\*\*|__|[*_#>|]/g, '')
    .replace(/[  ]/g, ' ')
    .replace(/(\d+)\.(\d)\d*/g, (_, a: string, b: string) => (Number(b) >= 5 ? String(Number(a) + 1) : a))
  for (const [pattern, words] of UNIT_WORDS) text = text.replace(pattern, words)
  const sentences = text
    .split(/\n+/)
    .map((l) => l.replace(/^\s*[-•\d.)]+\s*/, '').trim())
    .filter(Boolean)
  return sentences.slice(0, 3).join('. ').replace(/\.\s*\./g, '.').replace(/[–—]/g, ', ')
}

let current: { stop: () => void } | null = null
let audioCtx: AudioContext | null = null
let unlocked = false

export function unlockAudio() {
  if (unlocked) return
  unlocked = true
  try {
    audioCtx = audioCtx ?? new AudioContext()
    if (audioCtx.state === 'suspended') void audioCtx.resume()
    const silent = audioCtx.createBuffer(1, 1, 22050)
    const source = audioCtx.createBufferSource()
    source.buffer = silent
    source.connect(audioCtx.destination)
    source.start()
  } catch {
    unlocked = false
  }
  if ('speechSynthesis' in window) {
    const warm = new SpeechSynthesisUtterance(' ')
    warm.volume = 0
    window.speechSynthesis.speak(warm)
  }
}

export function stopSpeaking() {
  current?.stop()
  current = null
  window.speechSynthesis?.cancel()
}

function pickVoice(lang: string) {
  const voices = window.speechSynthesis.getVoices()
  const base = lang.split('-')[0]
  const matches = voices.filter((v) => v.lang === lang || v.lang.replace('_', '-').startsWith(`${base}-`) || v.lang === base)
  const score = (v: SpeechSynthesisVoice) =>
    (/natural|neural/i.test(v.name) ? 4 : 0) + (/online/i.test(v.name) ? 2 : 0) + (/google/i.test(v.name) ? 2 : 0) + (v.lang === lang ? 1 : 0)
  return matches.sort((a, b) => score(b) - score(a))[0] ?? null
}

export function hasBrowserVoice(lang: string) {
  return 'speechSynthesis' in window && pickVoice(lang) !== null
}

function browserSpeak(text: string, lang: string, onEnd: () => void) {
  const synth = window.speechSynthesis
  synth.cancel()
  const chunks = text.match(/[^.!?।॥]+[.!?।॥]?/g)?.map((c) => c.trim()).filter(Boolean) ?? [text]
  const voice = pickVoice(lang)
  window.setTimeout(() => {
    chunks.forEach((chunk, i) => {
      const u = new SpeechSynthesisUtterance(chunk)
      u.lang = lang
      u.voice = voice
      u.rate = 0.98
      if (i === chunks.length - 1) {
        u.onend = onEnd
        u.onerror = onEnd
      }
      synth.speak(u)
    })
  }, 60)
}

const OPUS = typeof Audio !== 'undefined' && new Audio().canPlayType('audio/ogg; codecs="opus"') !== ''

async function playWav(data: ArrayBuffer, onStart: () => void, onEnd: () => void) {
  audioCtx = audioCtx ?? new AudioContext()
  if (audioCtx.state === 'suspended') await audioCtx.resume()
  const buffer = await audioCtx.decodeAudioData(data)
  const source = audioCtx.createBufferSource()
  source.buffer = buffer
  source.connect(audioCtx.destination)
  source.onended = onEnd
  onStart()
  source.start()
  return () => {
    source.onended = null
    try {
      source.stop()
    } catch {
      return
    }
  }
}

export interface SpeakCallbacks {
  onStart: () => void
  onEnd: () => void
  onError: (message: string) => void
}

const SCRIPT_LANGS: [number, number, string][] = [
  [0x0900, 0x097f, 'hi-IN'],
  [0x0980, 0x09ff, 'bn-IN'],
  [0x0a00, 0x0a7f, 'pa-IN'],
  [0x0a80, 0x0aff, 'gu-IN'],
  [0x0b00, 0x0b7f, 'or-IN'],
  [0x0b80, 0x0bff, 'ta-IN'],
  [0x0c00, 0x0c7f, 'te-IN'],
  [0x0c80, 0x0cff, 'kn-IN'],
  [0x0d00, 0x0d7f, 'ml-IN'],
  [0x0600, 0x06ff, 'ur-IN'],
]

function speechLangFor(text: string, fallback: string) {
  const counts = new Map<string, number>()
  let latin = 0
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0
    if (/[a-z]/i.test(ch)) latin++
    const hit = SCRIPT_LANGS.find(([lo, hi]) => code >= lo && code <= hi)
    if (hit) counts.set(hit[2], (counts.get(hit[2]) ?? 0) + 1)
  }
  const [best, n] = [...counts.entries()].sort((a, b) => b[1] - a[1])[0] ?? ['', 0]
  if (!best || latin > n) return fallback.startsWith('en') ? fallback : 'en-IN'
  return fallback.split('-')[0] === best.split('-')[0] || (best === 'hi-IN' && fallback === 'mr-IN') || (best === 'bn-IN' && fallback === 'as-IN') ? fallback : best
}

export async function speak(text: string, menuLang: string, code: string, neural: boolean, cb: SpeakCallbacks) {
  const lang = speechLangFor(text, menuLang)
  stopSpeaking()
  let cancelled = false
  let stopAudio: (() => void) | null = null
  const controller = new AbortController()
  const handle = {
    stop: () => {
      cancelled = true
      controller.abort()
      stopAudio?.()
      window.speechSynthesis?.cancel()
      cb.onEnd()
    },
  }
  current = handle
  const finish = () => {
    if (current === handle) current = null
    cb.onEnd()
  }
  let neuralProblem = ''
  if (neural) {
    try {
      const response = await fetch(`${BASE}/api/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language: code, format: OPUS ? 'opus' : 'wav' }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `voice server error ${response.status}`)
      const data = await response.arrayBuffer()
      if (cancelled) return
      stopAudio = await playWav(data, cb.onStart, finish)
      return
    } catch (err) {
      if (cancelled) return
      neuralProblem = (err as Error).message
    }
  }
  if (!hasBrowserVoice(lang)) {
    if (current === handle) current = null
    cb.onError(
      neuralProblem
        ? `Voice unavailable: ${neuralProblem.includes('quota') || neuralProblem.includes('429') ? 'the free neural-voice limit is used up for today' : neuralProblem}. This browser has no ${lang} voice to fall back on.`
        : `This browser has no ${lang} voice installed.`,
    )
    return
  }
  cb.onStart()
  browserSpeak(text, lang, finish)
}

interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}

interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: { resultIndex: number; results: ArrayLike<RecognitionResult> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}

type RecognitionCtor = new () => Recognition

const RecognitionImpl: RecognitionCtor | undefined =
  (window as unknown as { SpeechRecognition?: RecognitionCtor }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition

const canRecord = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia

export type ListenPhase = 'idle' | 'listening' | 'transcribing'

export function useListen(lang: string, speechLang: string, serverStt: boolean, onFinal: (text: string) => void) {
  const [phase, setPhase] = useState<ListenPhase>('idle')
  const [interim, setInterim] = useState('')
  const [level, setLevel] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const stopRef = useRef<() => void>(() => undefined)
  const onFinalRef = useRef(onFinal)
  onFinalRef.current = onFinal

  const useServer = serverStt && canRecord

  const startServer = useCallback(async () => {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
    } catch {
      setError('Microphone permission was denied. Allow the mic in the browser to talk to WeatherGPT.')
      return
    }
    const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((m) => MediaRecorder.isTypeSupported(m)) ?? ''
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    const chunks: Blob[] = []
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    ctx.createMediaStreamSource(stream).connect(analyser)
    const samples = new Float32Array(analyser.fftSize)
    const started = performance.now()
    let heardSpeech = false
    let lastLoud = performance.now()
    let raf = 0
    let finished = false

    const finish = () => {
      if (finished) return
      finished = true
      cancelAnimationFrame(raf)
      if (recorder.state !== 'inactive') recorder.stop()
    }

    const watch = () => {
      analyser.getFloatTimeDomainData(samples)
      let sum = 0
      for (const s of samples) sum += s * s
      const rms = Math.sqrt(sum / samples.length)
      setLevel(Math.min(rms * 12, 1))
      const now = performance.now()
      if (rms > 0.02) {
        heardSpeech = true
        lastLoud = now
      }
      if ((heardSpeech && now - lastLoud > 1400) || (!heardSpeech && now - started > 7000) || now - started > 20000) {
        finish()
        return
      }
      raf = requestAnimationFrame(watch)
    }

    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop())
      ctx.close()
      setLevel(0)
      if (!heardSpeech) {
        setPhase('idle')
        setError("I didn't hear anything. Tap the mic and speak.")
        return
      }
      setPhase('transcribing')
      const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
      const form = new FormData()
      form.append('audio', blob, `speech.${(recorder.mimeType || 'audio/webm').includes('mp4') ? 'mp4' : 'webm'}`)
      form.append('language', lang)
      try {
        const response = await fetch(`${BASE}/api/transcribe`, { method: 'POST', body: form })
        if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? `Transcription failed (${response.status})`)
        const { text } = (await response.json()) as { text: string }
        setPhase('idle')
        if (text.trim()) onFinalRef.current(text.trim())
        else setError("Couldn't make out the words. Please try again.")
      } catch (err) {
        setPhase('idle')
        setError((err as Error).message)
      }
    }
    stopRef.current = finish
    setError(null)
    setInterim('')
    setPhase('listening')
    recorder.start(250)
    raf = requestAnimationFrame(watch)
  }, [lang])

  const startBrowser = useCallback(() => {
    if (!RecognitionImpl) {
      setError('Voice input needs Chrome or Edge, or a Groq key on the server.')
      return
    }
    const rec = new RecognitionImpl()
    rec.lang = speechLang
    rec.interimResults = true
    rec.continuous = false
    let finalText = ''
    rec.onresult = (e) => {
      let live = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        if (r.isFinal) finalText += r[0].transcript
        else live += r[0].transcript
      }
      setInterim(finalText + live)
    }
    rec.onerror = (e) => {
      if (e.error === 'network') setError('Browser speech recognition needs internet (Chrome/Edge).')
      else if (e.error === 'not-allowed') setError('Microphone permission was denied.')
      else if (e.error !== 'aborted' && e.error !== 'no-speech') setError(`Voice error: ${e.error}`)
    }
    rec.onend = () => {
      setPhase('idle')
      setInterim('')
      if (finalText.trim()) onFinalRef.current(finalText.trim())
    }
    stopRef.current = () => rec.stop()
    setError(null)
    setPhase('listening')
    rec.start()
  }, [speechLang])

  const start = useCallback(() => {
    stopSpeaking()
    if (useServer) startServer()
    else startBrowser()
  }, [useServer, startServer, startBrowser])

  const stop = useCallback(() => stopRef.current(), [])

  useEffect(() => () => stopRef.current(), [])

  return { supported: useServer || Boolean(RecognitionImpl), engine: useServer ? 'whisper' : 'browser', phase, interim, level, error, start, stop }
}
