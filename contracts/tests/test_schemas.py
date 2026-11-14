import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from contracts.schemas import EventPayload, ManualCheckPayload, RiskAssessment, TelemetryPayload

CONTRACTS = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,model", [
    ("telemetry.example.json", TelemetryPayload), ("telemetry-no-data.example.json", TelemetryPayload),
    ("event.example.json", EventPayload), ("event-crew_checkin.example.json", EventPayload),
    ("event-inactivity.example.json", EventPayload), ("check.example.json", ManualCheckPayload),
    ("assessment.example.json", RiskAssessment),
])
def test_existing_contract_examples_validate(name, model):
    value = json.loads((CONTRACTS / name).read_text())
    assert model.model_validate(value).model_dump(mode="json") == value


def test_sensor_numbers_accept_integral_floats_but_not_bool():
    msg = json.loads((CONTRACTS / "telemetry.example.json").read_text())
    msg["cabin"]["humidity_pct"] = 45.0
    assert TelemetryPayload.model_validate(msg).cabin.humidity_pct == 45
    msg["vitals"]["heart_rate_bpm"] = True
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate(msg)


def test_timezone_is_required_and_missing_manual_fields_stay_null():
    with pytest.raises(ValidationError):
        ManualCheckPayload(crew_id="x", ts="2026-11-14T12:00:00")
    check = ManualCheckPayload(crew_id="x", ts="2026-11-14T12:00:00Z")
    assert check.mood is None and check.blood_pressure is None and check.glucose_mg_dl is None
