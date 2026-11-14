// ④ Un único WebSocket con mensajes { type, data }. Reconecta con espera
// creciente (1, 2, 4… s, hasta 30 s), igual que el resto del proyecto.
import { wsUrl } from '@/config'

export function connectSocket(onMessage, onStatus) {
  let ws = null
  let retry = 0
  let timer = null
  let closed = false

  function open() {
    onStatus('connecting')
    ws = new WebSocket(wsUrl())
    ws.onopen = () => {
      retry = 0
      onStatus('online')
    }
    ws.onmessage = (e) => {
      let msg
      try {
        msg = JSON.parse(e.data)
      } catch {
        return
      }
      if (msg && typeof msg.type === 'string') onMessage(msg)
    }
    ws.onclose = () => {
      if (closed) return
      onStatus('offline')
      timer = setTimeout(open, Math.min(30_000, 1000 * 2 ** retry++))
    }
  }

  open()
  return () => {
    closed = true
    clearTimeout(timer)
    ws?.close()
  }
}
