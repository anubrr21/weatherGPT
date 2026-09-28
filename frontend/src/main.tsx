import { Capacitor } from '@capacitor/core'
import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const PhoneSim = lazy(() => import('./phone/PhoneSim.tsx'))
const simulator = window.location.pathname.replace(/\/+$/, '') === '/phone'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {simulator ? (
      <Suspense fallback={null}>
        <PhoneSim />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
)

if ('serviceWorker' in navigator && import.meta.env.PROD && !Capacitor.isNativePlatform()) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => undefined))
}
