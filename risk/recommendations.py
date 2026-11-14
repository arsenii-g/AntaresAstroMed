"""Contramedida para cada código de umbral superado.

Los textos son criterio propio. Las acciones por nivel (avisar al oficial
médico en nivel 2, contactar con Tierra en nivel 3) salen de la guía del
equipo, sección 5.
"""

from __future__ import annotations

from .indicators import IndicatorResult, _fmt

COUNTERMEASURES = {
    "HR_HIGH": "Reposo sentado 10 minutos y repetir la medida de pulso",
    "HR_LOW": "Repetir la medida de pulso en reposo y comprobar el sensor",
    "BODY_TEMP_HIGH": "Hidratarse, bajar la actividad y repetir la temperatura en 30 minutos",
    "BODY_TEMP_LOW": "Abrigarse y repetir la temperatura en 30 minutos",
    "BP_SYS_HIGH": "Reposo 5 minutos y repetir la tensión",
    "BP_DIA_HIGH": "Reposo 5 minutos y repetir la tensión",
    "GLUCOSE_HIGH": "Repetir la glucosa en ayunas y revisar la última comida",
    "GLUCOSE_LOW": "Tomar 15 g de hidratos de absorción rápida y repetir la glucosa en 15 minutos",
    "MOOD_LOW": "Programar una conversación con el equipo de apoyo psicológico",
    "PUSHUPS_HIGH": "Revisar el plan de ejercicio de fuerza",
    "INACTIVITY_HIGH": "Hacer una serie de flexiones o moverse unos minutos",
    "CABIN_TEMP_HIGH": "Bajar la consigna de temperatura de la cabina",
    "CABIN_TEMP_LOW": "Subir la consigna de temperatura de la cabina",
    "HUMIDITY_HIGH": "Revisar el control de humedad de la cabina",
    "HUMIDITY_LOW": "Revisar el control de humedad de la cabina",
    "HEAT_INDEX_HIGH": "Bajar la temperatura de la cabina y beber agua",
    "CONDENSATION_LOW": "Aumentar la ventilación para evitar condensación",
}

LEVEL_ACTIONS = {
    2: "Avisar al oficial médico de la tripulación",
    3: "Contactar con los médicos en Tierra",
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
    """Aviso por cada tendencia que cruzará un umbral en 7 días, salvo que el
    indicador ya esté hoy en ese nivel o peor (criterio propio)."""
    today = {r.indicator: r.level or 0 for r in results}
    today["pushup_reps"] = today.get("pushup_drop_pct", 0)
    out = []
    for t in sorted(trends, key=lambda t: t.crosses_threshold_in_days or 99):
        if t.crosses_threshold_in_days is None or today.get(t.indicator, 0) >= t.threshold_level:
            continue
        out.append(f"Tendencia: {t.label.lower()} llegará a {_fmt(t.threshold)} {t.unit} "
                   f"en unos {_fmt(t.crosses_threshold_in_days)} días; vigilar en los próximos chequeos")
    return out
