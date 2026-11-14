"""Resumen en inglés para los médicos en Tierra (guía: nivel 3, "genera un
resumen listo para enviar").

Como el resto de textos del motor, va en inglés (decisión del equipo, 14/11/2026). Solo se genera cuando el
nivel global es 3. Textos: criterio propio.
"""

from __future__ import annotations

from .indicators import IndicatorResult, _fmt, load_thresholds, with_unit
from .recommendations import COUNTERMEASURES
from .trends import Trend

LEVEL_NAMES = {0: "green", 1: "amber", 2: "orange", 3: "red", None: "no data"}
SYSTEM_NAMES = {
    "cardiovascular": "Cardiovascular and metabolic",
    "neuro": "Neurobehavioral",
    "musculoskeletal": "Musculoskeletal",
    "environment": "Cabin environment",
}
def earth_summary(crew_id, ts, overall_level, systems, results: list[IndicatorResult],
                  trends: list[Trend]) -> str | None:
    if overall_level != 3:
        return None
    thresholds = load_thresholds()
    lines = [
        "ASTROMED MEDICAL SUMMARY",
        f"Crew member: {crew_id or 'unknown'}",
        f"Time (UTC): {ts}",
        "Overall level: 3 (red). Notify the onboard medical officer and request Earth consultation.",
        "",
        "Systems:",
    ]
    for name, system in systems.items():
        lines.append(f"- {SYSTEM_NAMES[name]}: {LEVEL_NAMES[system['level']]}")

    flagged = sorted((r for r in results if r.level), key=lambda r: -r.level)
    lines += ["", "Findings (worst first):"]
    for r in flagged:
        lines.append(f"- [{LEVEL_NAMES[r.level]}] {r.reason}")

    missing = [thresholds[r.indicator]["label"] for r in results if r.level is None]
    if missing:
        lines += ["", "No data: " + ", ".join(missing)]

    crossing = [t for t in trends if t.crosses_threshold_in_days is not None]
    if crossing:
        lines += ["", "7-day trends:"]
        for t in crossing:
            lines.append(f"- {t.label}: projected {with_unit(t.projected_7d, t.unit)} in 7 days; "
                         f"crosses {with_unit(t.threshold, t.unit)} in {_fmt(t.crosses_threshold_in_days)} days")

    actions = []
    for r in flagged:
        text = COUNTERMEASURES.get(r.code or "")
        if text and text not in actions:
            actions.append(text)
    if actions:
        lines += ["", "Onboard countermeasures:"] + [f"- {a}" for a in actions]

    lines += ["", "Demo data from an educational sensor kit. Not a medical-grade measurement."]
    return "\n".join(lines)
