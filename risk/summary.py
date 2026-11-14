"""Resumen en inglés para los médicos en Tierra (guía: nivel 3, "genera un
resumen listo para enviar").

Va en inglés por decisión del equipo (14/11/2026). Solo se genera cuando el
nivel global es 3. Textos: criterio propio.
"""

from __future__ import annotations

from .indicators import IndicatorResult, _fmt, load_thresholds
from .trends import Trend

LEVEL_NAMES = {0: "green", 1: "amber", 2: "orange", 3: "red", None: "no data"}
SYSTEM_NAMES = {
    "cardiovascular": "Cardiovascular and metabolic",
    "neuro": "Neurobehavioral",
    "musculoskeletal": "Musculoskeletal",
    "environment": "Cabin environment",
}
COUNTERMEASURES_EN = {
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


def earth_summary(crew_id, ts, overall_level, systems, results: list[IndicatorResult],
                  trends: list[Trend]) -> str | None:
    if overall_level != 3:
        return None
    thresholds = load_thresholds()
    lines = [
        "SPACEHEALTH MEDICAL SUMMARY",
        f"Crew member: {crew_id or 'unknown'}",
        f"Time (UTC): {ts}",
        f"Overall level: 3 (red). Onboard medical officer notified; Earth consultation requested.",
        "",
        "Systems:",
    ]
    for name, system in systems.items():
        lines.append(f"- {SYSTEM_NAMES[name]}: {LEVEL_NAMES[system['level']]}")

    flagged = sorted((r for r in results if r.level), key=lambda r: -r.level)
    lines += ["", "Findings (worst first):"]
    for r in flagged:
        spec = thresholds[r.indicator]
        relation = "above" if r.code and r.code.endswith("_HIGH") else "below"
        unit = spec.get("unit_en", spec["unit"])
        lines.append(f"- [{LEVEL_NAMES[r.level]}] {spec.get('label_en', spec['label'])}: "
                     f"{_en(r.value)} {unit}, {relation} {_en(r.cut)} {unit}")

    missing = [thresholds[r.indicator].get("label_en", r.indicator) for r in results if r.level is None]
    if missing:
        lines += ["", "No data: " + ", ".join(missing)]

    crossing = [t for t in trends if t.crosses_threshold_in_days is not None]
    if crossing:
        lines += ["", "7-day trends:"]
        for t in crossing:
            spec = thresholds.get(t.indicator, {})
            label = spec.get("label_en", "Push-ups per set" if t.indicator == "pushup_reps" else t.indicator)
            unit = spec.get("unit_en", "reps" if t.indicator == "pushup_reps" else t.unit)
            lines.append(f"- {label}: projected {_en(t.projected_7d)} {unit} in 7 days; "
                         f"crosses {_en(t.threshold)} {unit} in {_en(t.crosses_threshold_in_days)} days")

    actions = []
    for r in flagged:
        text = COUNTERMEASURES_EN.get(r.code or "")
        if text and text not in actions:
            actions.append(text)
    if actions:
        lines += ["", "Onboard countermeasures:"] + [f"- {a}" for a in actions]

    lines += ["", "Demo data from an educational sensor kit. Not a medical-grade measurement."]
    return "\n".join(lines)


def _en(number) -> str:
    """Formato inglés: punto decimal."""
    return "?" if number is None else _fmt(number).replace(",", ".")
