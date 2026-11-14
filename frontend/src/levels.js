// Niveles del contrato ③. La web NUNCA calcula niveles: solo traduce el número
// que manda el motor a color y texto. `null` = sin dato, gris, nunca verde.

export const LEVELS = {
  0: { key: 'green', name: 'Green', title: 'All clear', hint: 'All systems within range' },
  1: { key: 'amber', name: 'Amber', title: 'Caution', hint: 'Something is out of range. Follow the recommendations' },
  2: { key: 'orange', name: 'Orange', title: 'Warning', hint: 'Notify the crew medical officer' },
  3: { key: 'red', name: 'Red', title: 'Alert!', hint: 'Critical. Send the summary to Earth' },
}

export const NO_DATA = { key: 'none', name: 'No data', title: 'No data', hint: 'No readings yet for this crew member' }

export function levelInfo(level) {
  const info = level == null ? NO_DATA : LEVELS[level] ?? NO_DATA
  return { ...info, level: level ?? null, color: `var(--lvl-${info.key})`, ink: `var(--ink-${info.key})` }
}

/** Orden de gravedad para listas: rojo primero, "sin dato" al final. */
export function severity(level) {
  return level == null ? -1 : level
}

export const SYSTEMS = {
  neuro: { label: 'Neuro', zone: 'Head', measures: 'mood' },
  cardiovascular: { label: 'Cardiovascular', zone: 'Chest', measures: 'heart rate, temperature, blood pressure, glucose' },
  musculoskeletal: { label: 'Musculoskeletal', zone: 'Arms and legs', measures: 'push-ups, inactivity' },
  environment: { label: 'Cabin', zone: 'Cabin', measures: 'temperature, humidity, heat index, condensation' },
}

export const BODY_SYSTEMS = ['neuro', 'cardiovascular', 'musculoskeletal']
