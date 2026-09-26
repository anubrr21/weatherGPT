import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const args = process.argv.slice(2)
const flag = (name) => args.includes(`--${name}`)
const option = (name, fallback) => {
  const i = args.indexOf(`--${name}`)
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback
}

const api = option('api', process.env.WEATHERGPT_API ?? 'http://localhost:8000').replace(/\/$/, '')
const release = flag('release')
const install = flag('install')
const push = existsSync(join(root, 'android', 'app', 'google-services.json'))
const windows = process.platform === 'win32'
const sdk = process.env.ANDROID_HOME ?? process.env.ANDROID_SDK_ROOT ?? (windows ? join(process.env.LOCALAPPDATA ?? '', 'Android', 'Sdk') : join(process.env.HOME ?? '', 'Android', 'Sdk'))
const adb = join(sdk, 'platform-tools', windows ? 'adb.exe' : 'adb')
const env = { ...process.env, ANDROID_HOME: sdk, WEATHERGPT_API: api, VITE_API_BASE: api, VITE_PUSH: push ? '1' : '0' }

const run = (cmd, cmdArgs, cwd = root) => {
  console.log(`\n> ${cmd} ${cmdArgs.join(' ')}`)
  execFileSync(cmd, cmdArgs, { cwd, env, stdio: 'inherit', shell: windows })
}

console.log(`API ${api} · push ${push ? 'on (google-services.json found)' : 'off (no google-services.json)'} · ${release ? 'release' : 'debug'}`)
run('npm', ['run', 'build'])
run('npx', ['cap', 'sync', 'android'])
run(join(root, 'android', windows ? 'gradlew.bat' : 'gradlew'), [release ? 'assembleRelease' : 'assembleDebug', '--console=plain'], join(root, 'android'))

const variant = release ? 'release' : 'debug'
const built = join(root, 'android', 'app', 'build', 'outputs', 'apk', variant, `app-${variant}${release ? '-unsigned' : ''}.apk`)
const out = join(root, 'dist-android')
mkdirSync(out, { recursive: true })
const apk = join(out, `WeatherGPT-${variant}.apk`)
if (existsSync(built)) {
  copyFileSync(built, apk)
  console.log(`\nAPK: ${apk}`)
}

if (install) {
  if (/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(api)) {
    const port = new URL(api).port || '80'
    run(adb, ['reverse', `tcp:${port}`, `tcp:${port}`])
  }
  run(adb, ['install', '-r', apk])
  run(adb, ['shell', 'am', 'start', '-n', 'in.weathergpt.app/.MainActivity'])
}
