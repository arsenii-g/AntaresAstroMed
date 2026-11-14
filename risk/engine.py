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

from .indicators import IndicatorResult, as_number, level_for, load_thresholds, restate, with_unit, _fmt
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
        now: hora actual, datetime CON zona horaria: datetime.now(timezone.utc).
            Sin zona lanza ValueError: un datetime.now() local en UTC+1 haría
            que toda la telemetría pareciera de hace una hora.

    Returns:
        La evaluación ③ (contracts/assessment.example.json). El nivel de un
        sistema sin ningún dato, y overall_level si no hay ninguno, es None.

    Nunca lanza excepciones por datos ausentes, incompletos o con basura.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("evaluate(now=...) needs a timezone-aware datetime: datetime.now(timezone.utc)")
    now = now.astimezone(timezone.utc)
    telemetry = _sorted_recent(telemetry, now, TELEMETRY_MAX_AGE)
    checks_week = _sorted_recent(manual_checks, now, HISTORY_WINDOW)
    checks_today = [c for c in checks_week if _parse_ts(c.get("ts")) >= now - CHECK_MAX_AGE]
    events = _sorted_recent(events, now, HISTORY_WINDOW)

    results = (
        _telemetry_indicators(telemetry, events, now)
        + _check_indicators(checks_today, checks_week)
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

def _telemetry_indicators(telemetry: list[dict], events: list[dict], now: datetime) -> list[IndicatorResult]:
    motion = lambda m: _obj(m.get("motion"))
    cabin = lambda m: _obj(m.get("cabin"))

    def margin(m):
        temp, dew = as_number(cabin(m).get("temp_c")), as_number(cabin(m).get("dew_point_c"))
        if temp is None or dew is None:
            return None
        return round(temp - dew, 1)

    getters = {
        "still_for_s": lambda m: motion(m).get("still_for_s"),
        "cabin_temp_c": lambda m: cabin(m).get("temp_c"),
        "humidity_pct": lambda m: cabin(m).get("humidity_pct"),
        "heat_index_c": lambda m: cabin(m).get("heat_index_c"),
        "condensation_margin_c": margin,
    }
    # El dato más reciente que no sea None dentro de la ventana de 60 s.
    return [_heart_rate(telemetry, events, now), _body_temp(telemetry)] + [
        level_for(name, _latest(telemetry, get)) for name, get in getters.items()
    ]


def _vital(message: dict, name: str):
    return as_number(_obj(message.get("vitals")).get(name))


def _sustained(telemetry: list[dict], indicator: str) -> IndicatorResult:
    """Nivel de un signo vital con la regla de lecturas sostenidas (criterio
    propio, ver risk/README.md, sección 3):

    - Ámbar con una sola lectura: avisar pronto no cuesta nada.
    - Naranja o rojo solo si las sustain_readings últimas lecturas están en
      ese nivel o peor. Mientras no, ámbar: nunca verde, para que un fallo
      del sensor no esconda un problema real.
    - Lecturas altas y bajas mezcladas en la ventana: ámbar y revisar el
      sensor, porque la señal no es fiable.
    """
    need = load_thresholds()[indicator].get("sustain_readings", 1)
    window = [level_for(indicator, v) for m in telemetry if (v := _vital(m, indicator)) is not None][-need:]
    if not window:
        return level_for(indicator, None)
    latest = window[-1]
    flagged = [r for r in window if r.level]
    if len({r.code for r in flagged}) > 1:
        return restate(flagged[-1], 1, "inconsistent readings; check the sensor")
    worst = max(reversed(window), key=lambda r: r.level)      # si empatan, la más reciente
    if worst.level < 2:
        return latest
    floor = min(r.level for r in window) if len(window) == need else 0
    if floor >= 2:
        held = next(r for r in reversed(window) if r.level == floor)
        return restate(held, floor, f"sustained over {need} readings")
    high = sum(1 for r in window if r.level >= 2)
    return restate(worst, 1, f"not sustained yet: {high} of {need} readings")


def _body_temp(telemetry: list[dict]) -> IndicatorResult:
    """Temperatura corporal: lecturas sostenidas (_sustained) y, además, la
    baja da como mucho low_max_level (ámbar). El termistor va en la muñeca, y
    la piel se enfría con la cabina aunque el tripulante esté bien (Polar,
    ver thresholds.json). Una muñeca fría pide un termómetro, no llamar a
    Tierra. La alta (fiebre) mantiene sus niveles."""
    result = _sustained(telemetry, "body_temp_c")
    spec = load_thresholds()["body_temp_c"]
    if result.code == "BODY_TEMP_LOW" and "low_max_level" in spec:
        result = restate(result, min(result.level, spec["low_max_level"]), spec.get("low_note", ""))
    return result


def _heart_rate(telemetry: list[dict], events: list[dict], now: datetime) -> IndicatorResult:
    """Pulso: lecturas sostenidas (_sustained) y, además, margen tras
    ejercicio (criterio propio): si el tripulante se está moviendo o hizo
    flexiones en los últimos exercise_recovery_s, un pulso alto en naranja
    baja a ámbar, porque subir el pulso con el esfuerzo es normal. El rojo
    (más de 150 lpm) no se rebaja: eso ya no se explica por unas flexiones.
    """
    result = _sustained(telemetry, "heart_rate_bpm")
    spec = load_thresholds()["heart_rate_bpm"]
    if result.level == 2 and result.code == "HR_HIGH" and _recovering(telemetry, events, now, spec):
        result = restate(result, 1, "after exercise; recheck at rest")
    return result


def _recovering(telemetry, events, now, spec) -> bool:
    moving = bool(telemetry) and _obj(telemetry[-1].get("motion")).get("activity") == "moving"
    window = timedelta(seconds=spec.get("exercise_recovery_s", 0))
    recent_set = any(
        e.get("type") == "exercise_summary" and (ts := _parse_ts(e.get("ts"))) is not None
        and now - window <= ts <= now + timedelta(seconds=5)
        for e in events
    )
    return moving or recent_set


def _check_indicators(today: list[dict], week: list[dict]) -> list[IndicatorResult]:
    """today: chequeos de las últimas 24 h (dan el valor actual). week: los de
    7 días (dan la medida anterior de la tensión y la media del ánimo)."""
    bp = lambda c: _obj(c.get("blood_pressure"))
    return [
        _blood_pressure(today, week, "systolic_mmhg", lambda c: as_number(bp(c).get("systolic"))),
        _blood_pressure(today, week, "diastolic_mmhg", lambda c: as_number(bp(c).get("diastolic"))),
        level_for("glucose_mg_dl", _latest(today, lambda c: as_number(c.get("glucose_mg_dl")))),
        _mood(today, week),
    ]


def _blood_pressure(today: list[dict], week: list[dict], indicator: str, get) -> IndicatorResult:
    """La guía pide escalar con 140/90 "en dos medidas": el nivel 2 necesita
    dos medidas seguidas de nivel 2 o más. La última tiene que ser de las
    últimas 24 h; la anterior puede ser de cualquier día de los últimos 7.
    El nivel 3 cuenta con una sola."""
    if _latest(today, get) is None:
        return level_for(indicator, None)
    values = [get(c) for c in week if get(c) is not None]
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


def _mood(today: list[dict], week: list[dict]) -> IndicatorResult:
    """Ánimo con los cortes fijos y, además, frente a la media del propio
    tripulante: ámbar si hoy está personal_drop puntos o más por debajo de la
    media de los chequeos anteriores de 7 días (criterio propio)."""
    get = lambda c: as_number(c.get("mood"))
    fixed = level_for("mood", _latest(today, get))
    if fixed.value is None or fixed.level:
        return fixed
    spec = load_thresholds()["mood"]
    values = [v for c in week if (v := get(c)) is not None]
    previous = values[:-1]
    if len(previous) < spec.get("personal_min_checks", 3):
        return fixed
    average = sum(previous) / len(previous)
    drop = average - fixed.value
    if drop < spec.get("personal_drop", 99):
        return fixed
    reason = (f"{spec['label']} {with_unit(fixed.value, spec['unit'])}, {_fmt(drop)} points "
              f"below own average {with_unit(average, spec['unit'])}")
    return IndicatorResult("mood", fixed.system, fixed.value, 1, f"{spec['code']}_LOW", reason,
                           round(average - spec["personal_drop"], 1))


def _exercise_indicators(events: list[dict]) -> list[IndicatorResult]:
    """Caída de flexiones de la última serie frente a la media de las anteriores
    de los últimos 7 días. Sin series previas no hay basal y no se evalúa."""
    reps = [
        as_number(_obj(e.get("data")).get("reps"))
        for e in events
        if e.get("type") == "exercise_summary"
    ]
    reps = [r for r in reps if r is not None]
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


def _obj(value) -> dict:
    """value si es un dict; si no (None, lista, texto…), un dict vacío."""
    return value if isinstance(value, dict) else {}


def _sorted_recent(messages: list[dict] | None, now: datetime, max_age: timedelta) -> list[dict]:
    """Mensajes dentro de la ventana, ordenados por ts, sin basura y sin
    duplicados. Un duplicado es el mismo (device_id, ts, type), como en la
    placa: si la API guarda dos veces un reintento, cuenta una sola vez."""
    out, seen = [], set()
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        ts = _parse_ts(m.get("ts"))
        key = (m.get("device_id"), m.get("ts"), m.get("type"))
        if ts is None or not now - max_age <= ts <= now + timedelta(seconds=5) or _seen(key, seen):
            continue
        out.append((ts, m))
    out.sort(key=lambda pair: pair[0])
    return [m for _, m in out]


def _seen(key: tuple, seen: set) -> bool:
    try:
        if key in seen:
            return True
        seen.add(key)
    except TypeError:          # device_id o type que no se pueden comparar: no se deduplica
        pass
    return False


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
            if isinstance(message.get("crew_id"), str) and message["crew_id"]:
                return message["crew_id"]
    return None


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
