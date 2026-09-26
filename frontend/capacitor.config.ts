import type { CapacitorConfig } from '@capacitor/cli'

const api = process.env.WEATHERGPT_API ?? ''
const cleartext = api.startsWith('http://')

const config: CapacitorConfig = {
  appId: 'in.weathergpt.app',
  appName: 'WeatherGPT',
  webDir: 'dist',
  backgroundColor: '#070b12',
  server: {
    androidScheme: 'https',
    cleartext,
  },
  android: {
    allowMixedContent: cleartext,
  },
  plugins: {
    SystemBars: {
      insetsHandling: 'native',
      initialViewportFit: 'cover',
    },
    SplashScreen: {
      launchShowDuration: 1200,
      launchAutoHide: false,
      backgroundColor: '#070b12',
      androidScaleType: 'CENTER_CROP',
      showSpinner: false,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    LocalNotifications: {
      smallIcon: 'ic_stat_weathergpt',
      iconColor: '#ff9933',
    },
  },
}

export default config
