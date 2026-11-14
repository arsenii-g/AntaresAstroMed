"""evaluate(): punto de entrada del motor de riesgos.

Pasos (guía del equipo, sección 5):
  1. Nivel por indicador contra thresholds.json (indicators.py).
  2. Nivel por sistema: el peor de sus indicadores.
  3. Tendencia a 7 días: regresión lineal de tensión, glucosa, ánimo y
     flexiones (trends.py).
  4. Recomendaciones: una contramedida por cada ámbar o peor, y un aviso por
     cada tendencia que cruce un umbral en 7 días.
  5. Resumen en inglés para Tierra cuando el nivel global es 3 (summary.py).

Un dato ausente es "no data" (sin dato), nunca verde. Todos los textos de
salida van en inglés. Si un sistema no tiene ningún dato,
su nivel es None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .indicators import IndicatorResult, level_for
from .recommendations import recommendations_for, trend_recommendations
from .summary import earth_summary
from .trends import trends_for

SYSTEMS = ("cardiovascular", "neuro", "musculoskeletal", "environment")

# Antigüedad máxima de un dato para darlo por válido (criterio propio).
TELEMETRY_MAX_AGE = timedelta(seconds=60)   # llega cada 5 s
CHECK_MAX_AGE = timedelta(hours=24)         # un chequeo manual al día
HISTORY_WINDOW = timedelta(days=7)          # basal de flexiones y tendencias


def evaluate(
    telemetry: list[dict],
    events: list[dict],
    manual_checks: list[dict],
    now: datetime,
) -> dict:
    """Evalúa el riesgo de un tripulante.

    Args:
        telemetry: mensajes ① de telemetría (contracts/telemetry.example.json),
            todos del mismo crew_id. Cualquier campo puede venir como None.
        events: eventos ① (crew_checkin, inactivity, exercise_summary) del
            mismo crew_id, de los últimos 7 días.
        manual_checks: chequeos manuales ② del mismo crew_id. Para la
            tendencia, la API debe pasar los de los últimos 7 días.
        now: hora actual, datetime con zona horaria UTC.

    Returns:
        La evaluación ③ (contracts/assessment.example.json). El nivel de un
        sistema sin ningún dato, y overall_level si no hay ninguno, es None.

    Nunca lanza excepciones por datos ausentes o incompletos.
    """
    now = _aware(now)
    telemetry = _sorted_recent(telemetry, now, TELEMETRY_MAX_AGE)
    checks_week = _sorted_recent(manual_checks, now, HISTORY_WINDOW)
    checks_today = [c for c in checks_week if _parse_ts(c.get("ts")) >= now - CHECK_MAX_AGE]
    events = _sorted_recent(events, now, HISTORY_WINDOW)

    results = (
        _telemetry_indicators(telemetry)
        + _check_indicators(checks_today)
        + _exercise_indicators(events)
    )
    trends = trends_for(checks_week, events, now, _parse_ts)

    systems = {}
    for name in SYSTEMS:
        own = [r for r in results if r.system == name]
        known = [r.level for r in own if r.level is not None]
        flagged = sorted((r for r in own if r.level), key=lambda r: -r.level)
        missing = [r for r in own if r.level is None]
        systems[name] = {
            "level": max(known) if known else None,
            "reasons": [r.reason for r in flagged + missing],
        }

    levels = [s["level"] for s in systems.values() if s["level"] is not None]
    overall = max(levels) if levels else None
    crew_id = _find_crew_id(telemetry, events, checks_week)
    recommendations = recommendations_for(results)
    for text in trend_recommendations(trends, results):
        if text not in recommendations:
            recommendations.append(text)
    return {
        "crew_id": crew_id,
        "ts": _iso(now),
        "overall_level": overall,
        "systems": systems,
        "trends": [t.as_dict() for t in trends],
        "recommendations": recommendations,
        "earth_summary": earth_summary(crew_id, _iso(now), overall, systems, results, trends),
    }


# --- indicadores ---------------------------------------------------------------

def _telemetry_indicators(telemetry: list[dict]) -> list[IndicatorResult]:
    vitals = lambda m: m.get("vitals") or {}
    motion = lambda m: m.get("motion") or {}
    cabin = lambda m: m.get("cabin") or {}

    def margin(m):
        c = cabin(m)
        if c.get("temp_c") is None or c.get("dew_point_c") is None:
            return None
        return round(c["temp_c"] - c["dew_point_c"], 1)

    getters = {
        "heart_rate_bpm": lambda m: vitals(m).get("heart_rate_bpm"),
        "body_temp_c": lambda m: vitals(m).get("body_temp_c"),
        "still_for_s": lambda m: motion(m).get("still_for_s"),
        "cabin_temp_c": lambda m: cabin(m).get("temp_c"),
        "humidity_pct": lambda m: cabin(m).get("humidity_pct"),
        "heat_index_c": lambda m: cabin(m).get("heat_index_c"),
        "condensation_margin_c": margin,
    }
    # El dato más reciente que no sea None dentro de la ventana de 60 s.
    return [level_for(name, _latest(telemetry, get)) for name, get in getters.items()]


def _check_indicators(checks: list[dict]) -> list[IndicatorResult]:
    bp = lambda c: c.get("blood_pressure") or {}
    results = [
        _blood_pressure(checks, "systolic_mmhg", lambda c: bp(c).get("systolic")),
        _blood_pressure(checks, "diastolic_mmhg", lambda c: bp(c).get("diastolic")),
        level_for("glucose_mg_dl", _latest(checks, lambda c: c.get("glucose_mg_dl"))),
        level_for("mood", _latest(checks, lambda c: c.get("mood"))),
    ]
    return results


def _blood_pressure(checks: list[dict], indicator: str, get) -> IndicatorResult:
    """La guía pide escalar con 140/90 "en dos medidas": el nivel 2 necesita
    dos medidas seguidas de nivel 2 o más. El nivel 3 cuenta con una sola."""
    values = [get(c) for c in checks if get(c) is not None]
    if not values:
        return level_for(indicator, None)
    last = level_for(indicator, values[-1])
    if last.level != 2:
        return last
    previous = level_for(indicator, values[-2]) if len(values) >= 2 else None
    if previous is not None and (previous.level or 0) >= 2:
        return last
    return IndicatorResult(
        last.indicator, last.system, last.value, 1, last.code,
        f"{last.reason} (first reading; confirm with a second one)", last.cut,
    )


def _exercise_indicators(events: list[dict]) -> list[IndicatorResult]:
    """Caída de flexiones de la última serie frente a la media de las anteriores
    de los últimos 7 días. Sin series previas no hay basal y no se evalúa."""
    reps = [
        (e.get("data") or {}).get("reps")
        for e in events
        if e.get("type") == "exercise_summary"
    ]
    reps = [r for r in reps if isinstance(r, (int, float))]
    if len(reps) < 2:
        return []
    baseline = sum(reps[:-1]) / len(reps[:-1])
    if baseline <= 0:
        return []
    drop = max(0.0, round((baseline - reps[-1]) / baseline * 100, 1))
    return [level_for("pushup_drop_pct", drop)]


# --- utilidades -----------------------------------------------------------------

def _latest(messages: list[dict], get):
    for message in reversed(messages):
        value = get(message)
        if value is not None:
            return value
    return None


def _sorted_recent(messages: list[dict] | None, now: datetime, max_age: timedelta) -> list[dict]:
    out = []
    for m in messages or []:
        ts = _parse_ts(m.get("ts"))
        if ts is not None and now - max_age <= ts <= now + timedelta(seconds=5):
            out.append((ts, m))
    out.sort(key=lambda pair: pair[0])
    return [m for _, m in out]


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _find_crew_id(*sources: list[dict]) -> str | None:
    for messages in sources:
        for message in reversed(messages):
            if message.get("crew_id"):
                return message["crew_id"]
    return None


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
