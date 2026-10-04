import { Capacitor } from '@capacitor/core'
import { Directory, Filesystem } from '@capacitor/filesystem'
import { Share } from '@capacitor/share'

function asBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Could not read the file'))
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '')
    reader.readAsDataURL(blob)
  })
}

function nameFrom(response: Response, fallback: string) {
  const header = response.headers.get('Content-Disposition') ?? ''
  const match = header.match(/filename="?([^";]+)"?/)
  return match ? match[1] : fallback
}

export async function downloadFile(url: string, fallbackName: string) {
  const response = await fetch(url)
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `Download failed (${response.status})`)
  }
  const blob = await response.blob()
  const name = nameFrom(response, fallbackName)
  if (Capacitor.isNativePlatform()) {
    const saved = await Filesystem.writeFile({ path: name, data: await asBase64(blob), directory: Directory.Cache })
    await Share.share({ title: name, url: saved.uri, dialogTitle: 'Save or share the report' })
    return name
  }
  const link = document.createElement('a')
  const href = URL.createObjectURL(blob)
  link.href = href
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(href), 4000)
  return name
}
