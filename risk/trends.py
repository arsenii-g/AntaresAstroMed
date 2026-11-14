"""Tendencias: una recta de mínimos cuadrados sobre las medidas reales del
propio tripulante, proyectada hacia delante.

Hay dos tipos de eje, según cómo llegan los datos:

- Por medida (basis "count"): chequeo manual (tensión, glucosa, ánimo) y
  series de flexiones. Cada medida es un paso: la última es x = 0, la
  anterior x = -1, y así. Se proyecta a 7 medidas más. Con un chequeo al día,
  7 chequeos son una semana; en una demo se pueden meter 7 seguidos y la
  recta sale igual de bien, porque no depende de cuánto tiempo pasa entre uno
  y otro.
- Por tiempo (basis "time"): telemetría del sensor (pulso, temperatura
  corporal, temperatura y humedad de cabina). x = segundos respecto a ahora,
  con la telemetría del último minuto que pasa la API. Se proyecta 60 s.

Criterio propio:
- Hacen falta al menos 7 medidas con valor para dibujar una recta.
- El umbral que se vigila es el siguiente que la recta todavía no ha pasado,
  en la dirección de la pendiente. crosses_in dice cuántos pasos (o
  segundos) faltan para que la recta lo cruce, o None si no lo cruza dentro
  del horizonte.
- El umbral de las flexiones se expresa en repeticiones: la basal (media de
  las series anteriores a la última) menos el porcentaje de caída del nivel.
- La temperatura corporal baja da como mucho ámbar (low_max_level), así que
  su tendencia hacia abajo solo vigila el corte de ámbar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .indicators import as_number, load_thresholds


def _obj(value) -> dict:
    return value if isinstance(value, dict) else {}


MIN_POINTS = 7
HORIZON_COUNT = 7          # medidas hacia delante (chequeos o series)
HORIZON_S = 60             # segundos hacia delante (telemetría)

CHECK_TRENDS = {
    "systolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("systolic"),
    "diastolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("diastolic"),
    "glucose_mg_dl": lambda c: c.get("glucose_mg_dl"),
    "mood": lambda c: c.get("mood"),
}
TELEMETRY_TRENDS = {
    "heart_rate_bpm": lambda m: _obj(m.get("vitals")).get("heart_rate_bpm"),
    "body_temp_c": lambda m: _obj(m.get("vitals")).get("body_temp_c"),
    "cabin_temp_c": lambda m: _obj(m.get("cabin")).get("temp_c"),
    "humidity_pct": lambda m: _obj(m.get("cabin")).get("humidity_pct"),
}
VALUE_LIMITS = {"mood": (1, 5), "pushup_reps": (0, None), "humidity_pct": (0, 100)}


@dataclass(frozen=True)
class Trend:
    indicator: str
    label: str
    unit: str
    basis: str                       # "count" o "time"
    x_unit: str                      # "check", "set" o "s"
    points: tuple                    # ((x, valor), ...) usados en el ajuste
    slope: float                     # por x_unit
    intercept: float                 # valor de la recta en x = 0
    horizon: float                   # hasta dónde se proyecta, en x_unit
    projected: float                 # valor de la recta en x = horizon
    threshold: float | None          # siguiente corte en la dirección de la pendiente
    threshold_level: int | None      # nivel al que llevaría ese corte
    crosses_in: float | None         # x_unit hasta cruzarlo; None si no llega en el horizonte

    def as_dict(self) -> dict:
        return {
            "indicator": self.indicator,
            "label": self.label,
            "unit": self.unit,
            "basis": self.basis,
            "x_unit": self.x_unit,
            "points": [list(p) for p in self.points],
            "slope": self.slope,
            "intercept": self.intercept,
            "horizon": self.horizon,
            "projected": self.projected,
            "threshold": self.threshold,
            "threshold_level": self.threshold_level,
            "crosses_in": self.crosses_in,
        }


def trends_for(telemetry: list[dict], checks: list[dict], events: list[dict],
               now: datetime, parse_ts) -> list[Trend]:
    """telemetry: último minuto; checks y events: últimos 7 días. Todo ya
    ordenado por ts y sin duplicados (lo hace engine.py)."""
    thresholds = load_thresholds()
    out = []

    for name, get in CHECK_TRENDS.items():
        values = [v for c in checks if (v := as_number(get(c))) is not None]
        trend = _fit(name, thresholds[name], _count_points(values), "count", "check", HORIZON_COUNT)
        if trend:
            out.append(trend)

    reps = [v for e in events if e.get("type") == "exercise_summary"
            and (v := as_number(_obj(e.get("data")).get("reps"))) is not None]
    if len(reps) >= MIN_POINTS:
        baseline = sum(reps[:-1]) / len(reps[:-1])
        drops = thresholds["pushup_drop_pct"].get("high", [])
        spec = {"label": "Push-ups per set", "unit": "reps", "high": [],
                "low": [None if d is None else round(baseline * (1 - d / 100), 1) for d in drops]}
        trend = _fit("pushup_reps", spec, _count_points(reps), "count", "set", HORIZON_COUNT)
        if trend:
            out.append(trend)

    for name, get in TELEMETRY_TRENDS.items():
        points = []
        for m in telemetry:
            value, ts = as_number(get(m)), parse_ts(m.get("ts"))
            if value is not None and ts is not None:
                points.append((round((ts - now).total_seconds(), 1), float(value)))
        trend = _fit(name, thresholds[name], points, "time", "s", HORIZON_S)
        if trend:
            out.append(trend)
    return out


def _count_points(values: list[float]) -> list[tuple[float, float]]:
    n = len(values)
    return [(float(i - (n - 1)), float(v)) for i, v in enumerate(values)]


def _fit(name, spec, points, basis, x_unit, horizon) -> Trend | None:
    if len(points) < MIN_POINTS:
        return None
    slope, intercept = _least_squares(points)
    high, low = list(spec.get("high", [])), list(spec.get("low", []))
    if "low_max_level" in spec:
        low = [cut if i < spec["low_max_level"] else None for i, cut in enumerate(low)]
    inclusive = spec.get("inclusive", False)

    now_value = intercept                       # la recta en x = 0
    # Solo se vigila el umbral hacia el que empeora: un pulso alto que baja, o
    # una humedad baja que sube, se están recuperando y no tienen umbral.
    above_high = _next_cut(now_value, high, above=True, inclusive=inclusive) != _first_cut(high)
    below_low = _next_cut(now_value, low, above=False, inclusive=inclusive) != _first_cut(low)
    found = None
    if slope > 0 and not below_low:
        found = _next_cut(now_value, high, above=True, inclusive=inclusive)
    elif slope < 0 and not above_high:
        found = _next_cut(now_value, low, above=False, inclusive=inclusive)

    threshold = level = crosses = None
    if found:
        threshold, level = found
        when = (threshold - intercept) / slope
        if 0 <= when <= horizon:
            crosses = round(max(when, 0.1), 1)

    return Trend(
        indicator=name, label=spec["label"], unit=spec["unit"], basis=basis, x_unit=x_unit,
        points=tuple((x, round(v, 2)) for x, v in points),
        slope=round(slope, 4), intercept=round(intercept, 2), horizon=horizon,
        projected=round(_clip(name, intercept + slope * horizon), 1),
        threshold=threshold, threshold_level=level, crosses_in=crosses,
    )


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


def _first_cut(cuts):
    """El primer corte que se usa, con su nivel (o None si no hay ninguno)."""
    return next(((cut, i) for i, cut in enumerate(cuts, start=1) if cut is not None), None)


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
