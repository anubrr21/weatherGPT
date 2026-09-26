import { useId } from 'react'

interface MarkProps {
  size?: number
  animated?: boolean
}

export function LogoMark({ size = 40, animated = true }: MarkProps) {
  const id = useId().replace(/:/g, '')
  const url = (name: string) => `url(#${name}-${id})`
  return (
    <svg className={`disha ${animated ? 'animated' : ''}`} width={size} height={size} viewBox="-8 -8 136 136" role="img" aria-label="weatherGPT compass logo">
      <defs>
        <radialGradient id={`core-${id}`} cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset=".5" stopColor="#ffb13b" />
          <stop offset="1" stopColor="#ff6a3d" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`snow-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#e6f4ff" />
          <stop offset="1" stopColor="#7fb2ff" />
        </linearGradient>
        <linearGradient id={`kite-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff4f8b" />
          <stop offset="1" stopColor="#d0283c" />
        </linearGradient>
        <linearGradient id={`dune-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f5c77e" />
          <stop offset="1" stopColor="#c7823a" />
        </linearGradient>
        <linearGradient id={`sea-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#5ec8ff" />
          <stop offset="1" stopColor="#1f6fd1" />
        </linearGradient>
      </defs>

      <circle className="ring" cx="60" cy="60" r="44" strokeWidth="1.4" />
      <circle className="ring" cx="60" cy="60" r="40" strokeWidth=".6" strokeDasharray="1.5 3.2" />
      <path className="tick" d="M60 16v5M60 99v5M16 60h5M99 60h5" />

      <path className="needle-l" d="M60 26 L65 55 L60 60 Z" />
      <path className="needle-d" d="M60 26 L55 55 L60 60 Z" />
      <path className="needle-sl" d="M60 94 L55 65 L60 60 Z" />
      <path className="needle-sd" d="M60 94 L65 65 L60 60 Z" />
      <path className="needle-l" d="M94 60 L65 65 L60 60 Z" />
      <path className="needle-d" d="M94 60 L65 55 L60 60 Z" />
      <path className="needle-l" d="M26 60 L55 55 L60 60 Z" />
      <path className="needle-d" d="M26 60 L55 65 L60 60 Z" />
      <g opacity=".75">
        <path className="needle-d" d="M79 41 L62 58 L64 60 Z" />
        <path className="needle-l" d="M79 41 L60 56 L62 58 Z" />
        <path className="needle-d" d="M41 79 L58 62 L56 60 Z" />
        <path className="needle-l" d="M41 79 L60 64 L58 62 Z" />
        <path className="needle-d" d="M41 41 L58 58 L60 56 Z" />
        <path className="needle-l" d="M41 41 L56 60 L58 58 Z" />
        <path className="needle-d" d="M79 79 L62 62 L60 64 Z" />
        <path className="needle-l" d="M79 79 L64 60 L62 62 Z" />
      </g>
      <circle className="core" cx="60" cy="60" r="10" fill={url('core')} />
      <circle cx="60" cy="60" r="3.2" fill="#fff8e6" />

      <g>
        <path d="M46 16 L60 1.5 L74 16 Z" fill="#6b76c9" />
        <path d="M53.5 8.7 L60 1.5 L66.5 8.7 L63.2 7.2 L60 9.6 L56.8 7.2 Z" fill={url('snow')} />
        <path d="M66 16 L70.5 9.5 L78 16 Z" fill="#4c57a8" />
      </g>

      <g className="wheel">
        <circle cx="104" cy="60" r="10.5" fill="none" stroke="#ffb13b" strokeWidth="2.2" />
        <circle cx="104" cy="60" r="7" fill="none" stroke="#ffb13b" strokeWidth=".8" strokeDasharray="1.2 1.6" />
        <path d="M104 50v20M94 60h20M97 53l14 14M111 53l-14 14" stroke="#ffcf6e" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="104" cy="60" r="2.6" fill="#d0283c" />
      </g>

      <g>
        <path d="M49 106 C 52 100, 58 100, 60 105 C 62 100, 68 100, 71 106" fill="none" stroke="#f7f0e3" strokeWidth="1.6" strokeLinecap="round" />
        <circle className="kolam-dot" cx="54" cy="110" r="2.3" />
        <circle className="kolam-dot" cx="60" cy="116" r="2.3" />
        <circle className="kolam-dot" cx="66" cy="110" r="2.3" />
      </g>

      <g className="kite">
        <path d="M16 47 L27 60 L16 73 L5 60 Z" fill={url('kite')} />
        <path d="M16 47 L27 60 L16 60 Z" fill="#ffcf3a" />
        <path d="M16 47 V73 M5 60 C 10 56, 22 56, 27 60" fill="none" stroke="#3a1024" strokeWidth=".9" />
        <path d="M16 73 c -2 4, 2 6, 0 10 c -2 3, 1 5, 0 7" fill="none" stroke="#ffcf3a" strokeWidth="1.2" strokeLinecap="round" />
      </g>

      <g transform="translate(97 23)">
        <path d="M-12 3 L0 -8 L12 3 Z" fill="#e1b04a" stroke="#7a4a12" strokeWidth=".8" />
        <path d="M-7.5 -1 L7.5 -1" stroke="#d0283c" strokeWidth="1.6" />
        <path d="M-4 -4.5 L4 -4.5" stroke="#1f7a3a" strokeWidth="1.2" />
        <path d="M-12 3 C -6 6, 6 6, 12 3" fill="none" stroke="#7a4a12" strokeWidth="1.2" />
        <g fill="#9fd8ff">
          <circle cx="-6" cy="8" r="1" />
          <circle cx="0" cy="10" r="1" />
          <circle cx="6" cy="8" r="1" />
        </g>
      </g>

      <g transform="translate(23 23)">
        <path d="M-13 6 C -7 -1, -1 -1, 4 4 C 7 1, 10 1, 13 5 L13 8 L-13 8 Z" fill={url('dune')} />
        <path d="M-13 8 C -8 4, -2 4, 3 8 Z" fill="#b8702e" opacity=".8" />
        <g className="shimmer" stroke="#ffd79a" strokeWidth="1" fill="none" strokeLinecap="round" opacity=".85">
          <path d="M-8 -4 c 2 -1.5, 4 1.5, 6 0" />
          <path d="M1 -7 c 2 -1.5, 4 1.5, 6 0" />
        </g>
        <circle cx="8" cy="-8" r="3.2" fill="#ffb13b" />
      </g>

      <g transform="translate(97 97)">
        <path d="M-13 6 c 3 -3, 6 -3, 9 0 c 3 -3, 6 -3, 9 0 c 3 -3, 6 -3, 8 0 L13 10 L-13 10 Z" fill={url('sea')} />
        <g className="cyclone" fill="none" stroke="#dff3ff" strokeWidth="1.6" strokeLinecap="round">
          <circle cx="0" cy="-4" r="2.2" />
          <path d="M0 -6.2 c 5 -3, 9 1, 7 4" />
          <path d="M0 -1.8 c -5 3, -9 -1, -7 -4" />
        </g>
      </g>

      <g transform="translate(23 97)">
        <g className="palm">
          <path d="M1 10 C 2 4, 1 -1, -1 -5" fill="none" stroke="#8a5a2b" strokeWidth="2" strokeLinecap="round" />
          <g fill="#3fae5a">
            <path d="M-1 -5 C -8 -8, -12 -4, -12 -1 C -8 -4, -5 -5, -1 -5 Z" />
            <path d="M-1 -5 C 5 -9, 10 -6, 11 -2 C 7 -5, 3 -5, -1 -5 Z" />
            <path d="M-1 -5 C -4 -11, 0 -14, 3 -13 C 1 -10, 0 -8, -1 -5 Z" />
            <path d="M-1 -5 C -6 -3, -8 1, -7 4 C -5 0, -3 -3, -1 -5 Z" />
          </g>
          <circle cx="-1" cy="-4" r="1.2" fill="#c98b2c" />
          <circle cx="0.5" cy="-3.2" r="1.2" fill="#c98b2c" />
        </g>
        <path d="M-12 11 C -6 8, 6 8, 12 11" fill="none" stroke="#5ec8ff" strokeWidth="1.4" strokeLinecap="round" />
      </g>
    </svg>
  )
}

export function Wordmark({ size = 32 }: { size?: number }) {
  return (
    <span className="wordmark" style={{ fontSize: size }}>
      <span className="wordmark-script">weather</span>
      <span className="wordmark-gpt" data-t="GPT">
        <span data-t="GPT">GPT</span>
      </span>
    </span>
  )
}

interface LogoProps {
  size?: number
  animated?: boolean
  wordmark?: boolean
  className?: string
}

export default function Logo({ size = 40, animated = true, wordmark = true, className = '' }: LogoProps) {
  return (
    <span className={`logo ${className}`}>
      <LogoMark size={size} animated={animated} />
      {wordmark && <Wordmark size={size * 0.52} />}
    </span>
  )
}
