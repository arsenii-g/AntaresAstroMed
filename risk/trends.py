"""Tendencia a 7 días (guía del equipo, sección 5).

Regresión lineal por mínimos cuadrados sobre los últimos 7 días del propio
tripulante, proyectada 7 días hacia delante. Avisa si la recta cruza el
siguiente umbral aunque hoy el valor esté en verde.

Solo se calcula para lo que llega pocas veces al día: tensión, glucosa y
ánimo (chequeo manual) y repeticiones de flexiones (evento exercise_summary).

Criterio propio:
- Hacen falta al menos 3 medidas que abarquen al menos 1 día.
- El umbral de las flexiones se expresa en repeticiones: la basal (media de las
  series anteriores a la última) menos el porcentaje de caída del nivel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .indicators import as_number, load_thresholds


def _obj(value) -> dict:
    return value if isinstance(value, dict) else {}

HORIZON_DAYS = 7
MIN_POINTS = 3
MIN_SPAN_DAYS = 1.0

# indicador de la tendencia -> (indicador de umbrales, cómo sacar el valor de un chequeo)
CHECK_TRENDS = {
    "systolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("systolic"),
    "diastolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("diastolic"),
    "glucose_mg_dl": lambda c: c.get("glucose_mg_dl"),
    "mood": lambda c: c.get("mood"),
}
VALUE_LIMITS = {"mood": (1, 5), "pushup_reps": (0, None)}


@dataclass(frozen=True)
class Trend:
    indicator: str
    label: str
    unit: str
    slope_per_day: float
    projected_7d: float
    threshold: float | None          # corte que cruzará; None si no cruza ninguno
    threshold_level: int | None       # nivel al que llegaría al cruzarlo
    crosses_threshold_in_days: float | None

    def as_dict(self) -> dict:
        return {
            "indicator": self.indicator,
            "projected_7d": self.projected_7d,
            "crosses_threshold_in_days": self.crosses_threshold_in_days,
            "threshold": self.threshold,
            "threshold_level": self.threshold_level,
            "slope_per_day": self.slope_per_day,
        }


def trends_for(checks: list[dict], events: list[dict], now: datetime, parse_ts) -> list[Trend]:
    """checks y events ya vienen ordenados y filtrados a los últimos 7 días."""
    thresholds = load_thresholds()
    out = []
    for name, get in CHECK_TRENDS.items():
        points = _points(checks, get, now, parse_ts)
        spec = thresholds[name]
        trend = _trend(name, spec["label"], spec["unit"], points, spec.get("high", []),
                       spec.get("low", []), spec.get("inclusive", False))
        if trend:
            out.append(trend)

    pushups = [e for e in events if e.get("type") == "exercise_summary"]
    points = _points(pushups, lambda e: _obj(e.get("data")).get("reps"), now, parse_ts)
    if len(points) >= 2:
        baseline = sum(v for _, v in points[:-1]) / len(points[:-1])
        drops = thresholds["pushup_drop_pct"].get("high", [])
        low_cuts = [None if d is None else round(baseline * (1 - d / 100), 1) for d in drops]
        trend = _trend("pushup_reps", "Push-ups per set", "reps", points, [], low_cuts, False)
        if trend:
            out.append(trend)
    return out


def _points(messages, get, now, parse_ts) -> list[tuple[float, float]]:
    points = []
    for m in messages:
        value, ts = as_number(get(m)), parse_ts(m.get("ts"))
        if value is not None and ts is not None:
            points.append(((ts - now).total_seconds() / 86400, float(value)))
    return points


def _trend(name, label, unit, points, high, low, inclusive) -> Trend | None:
    if len(points) < MIN_POINTS or points[-1][0] - points[0][0] < MIN_SPAN_DAYS:
        return None
    slope, intercept = _least_squares(points)          # x = días respecto a ahora
    projected = _clip(name, intercept + slope * HORIZON_DAYS)
    current = points[-1][1]

    threshold = level = days = None
    if slope > 0:
        found = _next_cut(current, high, above=True, inclusive=inclusive)
    elif slope < 0:
        found = _next_cut(current, low, above=False, inclusive=inclusive)
    else:
        found = None
    if found:
        cut, cut_level = found
        when = (cut - intercept) / slope
        if 0 < when <= HORIZON_DAYS:
            threshold, level, days = cut, cut_level, max(0.1, round(when, 1))

    return Trend(name, label, unit, round(slope, 2), round(projected, 1), threshold, level, days)


def _next_cut(current, cuts, *, above, inclusive):
    """Primer corte que el valor actual todavía no ha cruzado, con su nivel."""
    for i, cut in enumerate(cuts, start=1):
        if cut is None:
            continue
        if above:
            crossed = current >= cut if inclusive else current > cut
        else:
            crossed = current <= cut if inclusive else current < cut
        if not crossed:
            return cut, i
    return None


def _least_squares(points):
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    return slope, my - slope * mx


def _clip(name, value):
    lo, hi = VALUE_LIMITS.get(name, (None, None))
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value
