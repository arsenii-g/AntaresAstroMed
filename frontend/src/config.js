const env = import.meta.env

export const API_BASE = env.VITE_API_BASE ?? ''
export const API_KEY = env.VITE_API_KEY || null

export function wsUrl() {
  if (env.VITE_WS_URL) return env.VITE_WS_URL
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}${env.VITE_WS_PATH || '/ws'}`
}

export function initialCrewId() {
  const fromUrl = new URLSearchParams(location.search).get('crew')
  return fromUrl || env.VITE_DEFAULT_CREW || null
}
