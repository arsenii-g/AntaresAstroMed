/** Un `null` del contrato se muestra como "—", nunca como 0. */
export function fmt(value, unit = '', digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value).toFixed(digits)
  return unit ? `${n} ${unit}` : n
}

export function fmtTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** ISO 8601 en UTC sin milisegundos, como el resto de contratos. */
export function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

/** True si `next` no es más antiguo que `current` (la placa reenvía mensajes atrasados). */
export function isNewer(next, current) {
  if (!current?.ts || !next?.ts) return true
  return Date.parse(next.ts) >= Date.parse(current.ts)
}
