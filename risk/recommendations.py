"""Contramedida para cada código de umbral superado, en inglés.

Los textos son criterio propio. Las acciones por nivel (avisar al oficial
médico en nivel 2, contactar con Tierra en nivel 3) salen de la guía del
equipo, sección 5.
"""

from __future__ import annotations

import math

from .indicators import IndicatorResult, _fmt, with_unit

COUNTERMEASURES = {
    "HR_HIGH": "Seated rest for 10 minutes, then repeat the heart rate reading",
    "HR_LOW": "Repeat the resting heart rate reading and check the sensor",
    "BODY_TEMP_HIGH": "Hydrate, reduce activity and repeat the temperature in 30 minutes",
    "BODY_TEMP_LOW": "Add a layer of clothing and repeat the temperature in 30 minutes",
    "BP_SYS_HIGH": "Rest for 5 minutes and repeat the blood pressure",
    "BP_DIA_HIGH": "Rest for 5 minutes and repeat the blood pressure",
    "GLUCOSE_HIGH": "Repeat fasting glucose and review the last meal",
    "GLUCOSE_LOW": "Take 15 g of fast-acting carbohydrate and repeat glucose in 15 minutes",
    "MOOD_LOW": "Schedule a talk with the psychological support team",
    "PUSHUPS_HIGH": "Review the strength training plan",
    "INACTIVITY_HIGH": "Do a set of push-ups or move for a few minutes",
    "CABIN_TEMP_HIGH": "Lower the cabin temperature set point",
    "CABIN_TEMP_LOW": "Raise the cabin temperature set point",
    "HUMIDITY_HIGH": "Check cabin humidity control",
    "HUMIDITY_LOW": "Check cabin humidity control",
    "HEAT_INDEX_HIGH": "Lower the cabin temperature and drink water",
    "CONDENSATION_LOW": "Increase ventilation to prevent condensation",
}

LEVEL_ACTIONS = {
    2: "Notify the crew medical officer",
    3: "Contact the medical team on Earth",
}


def recommendations_for(results: list[IndicatorResult]) -> list[str]:
    """Una contramedida por cada ámbar o peor, sin repetir, de la más grave a la menos."""
    flagged = sorted((r for r in results if r.level), key=lambda r: -r.level)
    out: list[str] = []
    worst = flagged[0].level if flagged else 0
    if worst in LEVEL_ACTIONS:
        out.append(LEVEL_ACTIONS[worst])
    for r in flagged:
        text = COUNTERMEASURES.get(r.code or "")
        if text and text not in out:
            out.append(text)
    return out


def trend_recommendations(trends, results: list[IndicatorResult]) -> list[str]:
    """Aviso por cada tendencia que cruzará un umbral dentro de su horizonte,
    salvo que el indicador ya esté hoy en ese nivel o peor (criterio propio).
    Primero las del sensor (segundos), luego las de chequeos y series."""
    today = {r.indicator: r.level or 0 for r in results}
    today["pushup_reps"] = today.get("pushup_drop_pct", 0)
    out = []
    for t in sorted(trends, key=lambda t: (t.basis != "time", t.crosses_in or 99)):
        if t.crosses_in is None or today.get(t.indicator, 0) >= t.threshold_level:
            continue
        target = with_unit(t.threshold, t.unit)
        if t.basis == "time":
            out.append(f"Trend: {t.label.lower()} is heading to {target} within {_fmt(t.crosses_in)} s; "
                       "recheck the reading")
        else:
            steps = math.ceil(t.crosses_in)
            noun = {"check": "daily check", "set": "push-up set"}.get(t.x_unit, t.x_unit)
            out.append(f"Trend: {t.label.lower()} will reach {target} in about {steps} more "
                       f"{noun}{'s' if steps != 1 else ''}; watch the next ones")
    return out
