import json
from datetime import datetime, timezone
from pathlib import Path

from risk import evaluate

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SYSTEMS = {"cardiovascular", "neuro", "musculoskeletal", "environment"}


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_devuelve_la_forma_del_contrato():
    now = datetime(2026, 11, 14, 10, 30, 5, tzinfo=timezone.utc)
    result = evaluate(
        telemetry=[load("telemetry.example.json")],
        events=[load("event.example.json")],
        manual_checks=[load("check.example.json")],
        now=now,
    )

    assert result["crew_id"] == "F3786E09"
    assert result["ts"] == "2026-11-14T10:30:05Z"
    assert result["overall_level"] in range(4)
    assert set(result["systems"]) == SYSTEMS
    for system in result["systems"].values():
        assert system["level"] in range(4)
        assert isinstance(system["reasons"], list)
    assert isinstance(result["trends"], list)
    assert isinstance(result["recommendations"], list)


def test_sin_datos_no_falla():
    result = evaluate([], [], [], datetime.now(timezone.utc))
    assert result["crew_id"] is None
    assert set(result["systems"]) == SYSTEMS
