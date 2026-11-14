// Cómo se dibuja un elemento de `trends` (③).
//
// El motor no manda los puntos de los 7 días: manda la recta de mínimos
// cuadrados (risk/trends.py), con x = días respecto a ahora:
//   valor(x) = intercepto + slope_per_day · x
//   projected_7d = valor(7)  →  intercepto = projected_7d − 7 · slope_per_day
// La gráfica pinta esa recta: de −7 a 0 días es el ajuste a los datos
// (línea continua) y de 0 a +7 la proyección (discontinua).

export const HORIZON_DAYS = 7

export const INDICATORS = {
  systolic_mmhg: { label: 'Systolic blood pressure', unit: 'mmHg', digits: 0 },
  diastolic_mmhg: { label: 'Diastolic blood pressure', unit: 'mmHg', digits: 0 },
  glucose_mg_dl: { label: 'Glucose', unit: 'mg/dL', digits: 0 },
  mood: { label: 'Mood', unit: '/5', digits: 1, min: 1, max: 5 },
  pushup_reps: { label: 'Push-ups per set', unit: 'reps', digits: 1, min: 0 },
}

export function indicatorInfo(name) {
  return INDICATORS[name] ?? { label: name, unit: '', digits: 1 }
}

/** Recta de la tendencia, recortada a los límites del indicador como hace el motor. */
export function trendLine(trend) {
  const info = indicatorInfo(trend.indicator)
  const slope = Number(trend.slope_per_day) || 0
  const intercept = Number(trend.projected_7d) - HORIZON_DAYS * slope
  return (x) => {
    let v = intercept + slope * x
    if (info.min != null) v = Math.max(info.min, v)
    if (info.max != null) v = Math.min(info.max, v)
    return v
  }
}
