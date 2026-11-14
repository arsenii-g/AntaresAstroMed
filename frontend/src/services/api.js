// Contratos ② y ④ por HTTP. La web solo habla con la API.
import { API_BASE, API_KEY } from '@/config'

function headers() {
  const h = { 'Content-Type': 'application/json' }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

/**
 * ④ GET /api/v1/crew/{id}/latest, al abrir la página y al reconectar.
 * La forma exacta de la respuesta está pendiente con la API: se acepta
 * `{ telemetry, assessment }` o directamente una evaluación ③.
 */
export async function fetchLatest(crewId) {
  const res = await fetch(`${API_BASE}/api/v1/crew/${encodeURIComponent(crewId)}/latest`, { headers: headers() })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`GET latest: HTTP ${res.status}`)
  const body = await res.json()
  if (body?.systems) return { telemetry: null, assessment: body }
  return { telemetry: body?.telemetry ?? null, assessment: body?.assessment ?? null }
}

/** ② POST /api/v1/checks al terminar el chequeo guiado. 409 = ya estaba guardado. */
export async function postCheck(check) {
  const res = await fetch(`${API_BASE}/api/v1/checks`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(check),
  })
  if (res.ok || res.status === 409) return { ok: true }
  let detail = ''
  try {
    detail = JSON.stringify((await res.json()).detail ?? '')
  } catch {
    /* cuerpo no JSON */
  }
  throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ''}`)
}
