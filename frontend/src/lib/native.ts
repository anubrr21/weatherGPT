import { App } from '@capacitor/app'
import { Capacitor, type PluginListenerHandle } from '@capacitor/core'
import { LocalNotifications } from '@capacitor/local-notifications'
import { PushNotifications } from '@capacitor/push-notifications'
import { SplashScreen } from '@capacitor/splash-screen'
import { StatusBar, Style } from '@capacitor/status-bar'
import { clientId, type LiveAlert } from './live'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const PUSH_BUILT = import.meta.env.VITE_PUSH === '1'
const CHANNEL = 'warnings'

export const isNative = Capacitor.isNativePlatform()

export type Permission = 'granted' | 'denied' | 'prompt' | 'unsupported'

export interface AlertTap {
  alertId: string
  place: string
  lat: number
  lon: number
}

export interface NativeHandlers {
  onBack: () => boolean
  onAlertTap: (tap: AlertTap) => void
}

const channel = {
  id: CHANNEL,
  name: 'Weather warnings',
  description: 'Official IMD and NDMA warnings for your saved places',
  importance: 5 as const,
  visibility: 1 as const,
  lights: true,
  lightColor: '#ff9933',
  vibration: true,
}

function numericId(text: string) {
  let hash = 0
  for (const ch of text) hash = (Math.imul(hash, 31) + ch.charCodeAt(0)) | 0
  return Math.abs(hash) % 2_000_000_000
}

function toTap(data: Record<string, unknown> | undefined): AlertTap | null {
  if (!data || typeof data.alert_id !== 'string') return null
  const lat = Number(data.lat)
  const lon = Number(data.lon)
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null
  return { alertId: data.alert_id, place: String(data.place ?? ''), lat, lon }
}

export async function notificationPermission(): Promise<Permission> {
  if (isNative) {
    const { display } = await LocalNotifications.checkPermissions()
    return display === 'granted' ? 'granted' : display === 'denied' ? 'denied' : 'prompt'
  }
  if (!('Notification' in window)) return 'unsupported'
  return Notification.permission === 'default' ? 'prompt' : Notification.permission
}

export async function requestNotificationPermission(): Promise<Permission> {
  if (isNative) {
    const { display } = await LocalNotifications.requestPermissions()
    if (display === 'granted') void registerPush()
    return display === 'granted' ? 'granted' : display === 'denied' ? 'denied' : 'prompt'
  }
  if (!('Notification' in window)) return 'unsupported'
  const result = await Notification.requestPermission()
  return result === 'default' ? 'prompt' : result
}

export async function notifyAlert(alert: LiveAlert) {
  const title = `${alert.alert.severity} · ${alert.alert.event ?? 'Weather alert'} — ${alert.place.name}`
  if (isNative) {
    if ((await notificationPermission()) !== 'granted') return
    await LocalNotifications.schedule({
      notifications: [
        {
          id: numericId(alert.alert.id),
          title,
          body: alert.alert.headline,
          largeBody: alert.alert.headline,
          channelId: CHANNEL,
          extra: { alert_id: alert.alert.id, place: alert.place.name, lat: alert.place.lat, lon: alert.place.lon },
        },
      ],
    }).catch(() => undefined)
    return
  }
  if (!('Notification' in window) || Notification.permission !== 'granted') return
  try {
    const n = new Notification(title, { body: alert.alert.headline, icon: '/favicon.svg', tag: alert.alert.id })
    n.onclick = () => window.focus()
  } catch {
    return
  }
}

let pushStarted = false

async function registerPush() {
  if (!isNative || !PUSH_BUILT || pushStarted) return
  const { receive } = await PushNotifications.checkPermissions()
  if (receive !== 'granted') return
  pushStarted = true
  await PushNotifications.register()
}

export async function unregisterDevice(token: string) {
  await fetch(`${BASE}/api/devices/unregister`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  }).catch(() => undefined)
}

export async function sendTestPush() {
  const response = await fetch(`${BASE}/api/devices/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id: clientId() }),
  })
  return (await response.json()) as { configured: boolean; sent: number; devices: number }
}

export const pushBuilt = PUSH_BUILT

let asked = false

export async function promptNotificationsOnce() {
  if (!isNative || asked) return
  asked = true
  try {
    const current = await notificationPermission()
    if (current === 'granted') await registerPush()
    else if (current === 'prompt') await requestNotificationPermission()
  } catch {
    return
  }
}

export function initNative(handlers: NativeHandlers) {
  if (!isNative) return () => undefined
  const listeners: Promise<PluginListenerHandle>[] = []

  StatusBar.setStyle({ style: Style.Dark }).catch(() => undefined)
  StatusBar.setBackgroundColor({ color: '#070b12' }).catch(() => undefined)
  window.setTimeout(() => SplashScreen.hide({ fadeOutDuration: 250 }).catch(() => undefined), 150)

  listeners.push(
    App.addListener('backButton', () => {
      if (!handlers.onBack()) App.minimizeApp().catch(() => undefined)
    }),
  )

  LocalNotifications.createChannel(channel).catch(() => undefined)
  listeners.push(
    LocalNotifications.addListener('localNotificationActionPerformed', ({ notification }) => {
      const tap = toTap(notification.extra as Record<string, unknown>)
      if (tap) handlers.onAlertTap(tap)
    }),
  )

  if (PUSH_BUILT) {
    PushNotifications.createChannel(channel).catch(() => undefined)
    listeners.push(
      PushNotifications.addListener('registration', ({ value }) => {
        fetch(`${BASE}/api/devices`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ client_id: clientId(), token: value, platform: 'android' }),
        }).catch(() => undefined)
      }),
      PushNotifications.addListener('registrationError', () => {
        pushStarted = false
      }),
      PushNotifications.addListener('pushNotificationActionPerformed', ({ notification }) => {
        const tap = toTap(notification.data as Record<string, unknown>)
        if (tap) handlers.onAlertTap(tap)
      }),
    )
  }

  return () => {
    for (const listener of listeners) listener.then((l) => l.remove()).catch(() => undefined)
  }
}
