"""evaluate(): punto de entrada del motor de riesgos.

STUB: de momento devuelve siempre el ejemplo ③ de contracts/, con el crew_id
y la hora de la llamada. La firma y la forma de la respuesta ya son las
definitivas, así que la API puede integrarlo desde ahora; cuando llegue el
motor real, solo cambia lo de dentro.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parent.parent / "contracts" / "assessment.example.json"


def evaluate(
    telemetry: list[dict],
    events: list[dict],
    manual_checks: list[dict],
    now: datetime,
) -> dict:
    """Evalúa el riesgo de un tripulante.

    Args:
        telemetry: mensajes ① de telemetría (contracts/telemetry.example.json),
            todos del mismo crew_id. Los vitales pueden venir como None.
        events: eventos ① (contracts/event.example.json) del mismo crew_id.
        manual_checks: chequeos manuales ② (contracts/check.example.json)
            del mismo crew_id.
        now: hora actual, datetime con zona horaria UTC.

    Returns:
        La evaluación ③ (contracts/assessment.example.json): overall_level,
        systems (level y reasons de cada sistema), trends y recommendations.

    No lanza excepciones por datos ausentes: lo que falta se trata como
    "sin dato".
    """
    result = copy.deepcopy(_load_example())
    result["crew_id"] = _find_crew_id(telemetry, events, manual_checks)
    result["ts"] = _iso_utc(now)
    return result


def _load_example() -> dict:
    with _EXAMPLE.open(encoding="utf-8") as f:
        return json.load(f)


def _find_crew_id(*sources: list[dict]) -> str | None:
    for messages in sources:
        for message in messages or []:
            crew_id = message.get("crew_id")
            if crew_id:
                return crew_id
    return None


def _iso_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
