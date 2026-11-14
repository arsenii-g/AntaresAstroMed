import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import api.main as api_main
import api.services as services
from api.models import AssessmentModel, CheckModel, EventModel, RejectedMessage, TelemetryModel

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
AUTH = {"X-API-Key": "test-key"}
CREW = "F3786E09"


def stamp(moment):
    return moment.isoformat().replace("+00:00", "Z")


def example(name, **changes):
    value = json.loads((CONTRACTS / name).read_text())
    value["ts"] = stamp(NOW)
    value.update(changes)
    return value


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_main, "now_utc", lambda: NOW)
    app = api_main.create_app(f"sqlite:///{tmp_path / 'test.db'}", api_key="test-key")
    with TestClient(app) as client:
        yield client


def count(client, model):
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_frontend_and_offline_clock_are_served_together(client):
    root = client.get("/")
    assert root.status_code == 200 and "ArgosMed" in root.text
    assert root.headers["date"].endswith("GMT")
    assert client.get("/console.html").status_code == 200
    assert client.get("/js/app.js").status_code == 200
    assert client.get("/api/v1/status").json()["system"] == "ArgosMed"


def test_telemetry_evaluates_and_broadcasts_official_envelope(client):
    msg = example("telemetry.example.json")
    with client.websocket_connect("/ws") as ws:
        reply = client.post("/api/v1/telemetry", json=msg, headers=AUTH)
        assert reply.status_code == 200 and reply.json()["ok"]
        assert ws.receive_json() == {"type": "telemetry", "data": msg}
        assessment = ws.receive_json()
        assert assessment["type"] == "assessment"
        assert assessment["data"]["crew_id"] == CREW
        assert assessment["data"]["systems"]["cardiovascular"]["level"] == 0
    assert count(client, TelemetryModel) == count(client, AssessmentModel) == 1


def test_manual_check_is_public_and_updates_risk(client):
    check = example("check.example.json", blood_pressure={"systolic": 185, "diastolic": 100})
    with client.websocket_connect("/ws") as ws:
        assert client.post("/api/v1/checks", json=check).status_code == 200
        msg = ws.receive_json()
        assert msg["type"] == "assessment" and msg["data"]["overall_level"] == 3
        assert msg["data"]["earth_summary"].startswith("ARGOSMED MEDICAL SUMMARY")
    latest = client.get(f"/api/v1/crew/{CREW}/latest").json()
    assert latest["assessment"]["overall_level"] == 3
    assert count(client, CheckModel) == 1


@pytest.mark.parametrize("path,file,model", [
    ("telemetry", "telemetry.example.json", TelemetryModel),
    ("events", "event.example.json", EventModel),
    ("checks", "check.example.json", CheckModel),
])
def test_retries_are_idempotent(client, path, file, model):
    msg = example(file)
    first = client.post(f"/api/v1/{path}", json=msg, headers=AUTH)
    again = client.post(f"/api/v1/{path}", json=msg, headers=AUTH)
    assert first.json()["duplicate"] is False
    assert again.json() == {"ok": True, "duplicate": True, "assessment_pending": False}
    assert count(client, model) == count(client, AssessmentModel) == 1


def test_concurrent_hardware_retries_only_store_once(client):
    msg = example("telemetry.example.json")
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/telemetry", json=msg, headers=AUTH), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert count(client, TelemetryModel) == 1


def test_existing_database_messages_are_not_duplicated(client):
    msg = example("telemetry.example.json")
    with client.app.state.session_factory() as db:
        db.add(TelemetryModel(device_id=msg["device_id"], ts=NOW, met_s=msg["met_s"], crew_id=CREW, payload_data=msg))
        db.commit()
    assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).json()["duplicate"]
    assert count(client, TelemetryModel) == 1


def test_null_sensors_and_unassigned_data_are_accepted(client):
    msg = example("telemetry-no-data.example.json")
    response = client.post("/api/v1/telemetry", json=msg, headers=AUTH)
    assert response.status_code == 200
    assert count(client, TelemetryModel) == 1 and count(client, AssessmentModel) == 0
    latest = client.get(f"/api/v1/crew/{CREW}/latest").json()
    assert latest["assessment"]["overall_level"] is None


def test_unknown_crew_and_forward_compatible_fields_are_retained(client):
    msg = example("telemetry.example.json", crew_id="NEW-CARD", extra_field="retained")
    assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).status_code == 200
    latest = client.get("/api/v1/crew/NEW-CARD/latest").json()
    assert latest["assigned"] is False and latest["telemetry"]["extra_field"] == "retained"
    assert "NEW-CARD" in {c["crew_id"] for c in client.get("/api/v1/crew").json()}
    assert "336F8312" in {c["crew_id"] for c in client.get("/api/v1/crew").json()}


def test_invalid_measurement_is_logged_and_null_is_not_rejected(client):
    msg = example("telemetry.example.json")
    msg["vitals"]["heart_rate_bpm"] = 999
    assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).status_code == 422
    assert count(client, RejectedMessage) == 1
    assert count(client, TelemetryModel) == 0
    msg["vitals"]["heart_rate_bpm"] = None
    msg["vitals"]["body_temp_c"] = None
    assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).status_code == 200


def test_bad_json_and_key_responses_match_firmware(client):
    assert client.post("/api/v1/telemetry", content="{", headers={**AUTH, "Content-Type": "application/json"}).status_code == 400
    msg = example("telemetry.example.json")
    assert client.post("/api/v1/telemetry", json=msg).status_code == 401
    assert client.post("/api/v1/telemetry", json=msg, headers={"X-API-Key": "wrong"}).status_code == 401


def test_utc_offsets_filters_and_late_packets(client):
    newer = example("telemetry.example.json", ts="2026-11-14T13:00:00+01:00")
    older = example("telemetry.example.json", ts=stamp(NOW - timedelta(seconds=30)), met_s=1)
    for msg in (newer, older):
        assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).status_code == 200
    latest = client.get(f"/api/v1/crew/{CREW}/latest").json()
    assert latest["telemetry"]["met_s"] == newer["met_s"]
    rows = client.get(f"/api/v1/crew/{CREW}/telemetry", params={"from": stamp(NOW - timedelta(seconds=10)), "to": stamp(NOW)}).json()
    assert len(rows) == 1 and rows[0]["ts"] == stamp(NOW)
    assert client.get(f"/api/v1/crew/{CREW}/telemetry", params={"from": stamp(NOW), "to": stamp(NOW - timedelta(days=1))}).status_code == 422


def test_histories_are_isolated_by_crew_and_events_are_filterable(client):
    for crew in (CREW, "336F8312"):
        assert client.post("/api/v1/checks", json=example("check.example.json", crew_id=crew)).status_code == 200
        assert client.post("/api/v1/events", json=example("event.example.json", crew_id=crew, device_id=crew), headers=AUTH).status_code == 200
    rows = client.get("/api/v1/events", params={"crew_id": CREW, "type": "exercise_summary"}).json()
    assert len(rows) == 1 and rows[0]["crew_id"] == CREW
    assert len(client.get(f"/api/v1/crew/{CREW}/checks").json()) == 1


def test_one_week_of_history_reaches_real_trend_engine(client):
    for day in range(6, -1, -1):
        check = example("check.example.json", ts=stamp(NOW - timedelta(days=day, hours=1)), glucose_mg_dl=80 + 3 * (6 - day))
        assert client.post("/api/v1/checks", json=check).status_code == 200
    assessment = client.get(f"/api/v1/crew/{CREW}/latest").json()["assessment"]
    trend = next(t for t in assessment["trends"] if t["indicator"] == "glucose_mg_dl")
    assert trend["slope_per_day"] == pytest.approx(3)
    assert trend["crosses_threshold_in_days"] is not None


def test_engine_failure_does_not_lose_data_and_retry_recovers(client, monkeypatch):
    original = services.evaluate
    monkeypatch.setattr(services, "evaluate", lambda *a: (_ for _ in ()).throw(RuntimeError("test failure")))
    msg = example("telemetry.example.json")
    response = client.post("/api/v1/telemetry", json=msg, headers=AUTH)
    assert response.json()["ok"] and response.json()["assessment_pending"]
    assert count(client, TelemetryModel) == 1
    assert client.get(f"/api/v1/crew/{CREW}/latest").json()["assessment"] is None
    monkeypatch.setattr(services, "evaluate", original)
    recovered = client.post("/api/v1/telemetry", json=msg, headers=AUTH).json()
    assert recovered["duplicate"] and not recovered["assessment_pending"]
    assert count(client, TelemetryModel) == count(client, AssessmentModel) == 1


def test_reload_recomputes_expired_data(client, monkeypatch):
    msg = example("telemetry.example.json")
    client.post("/api/v1/telemetry", json=msg, headers=AUTH)
    monkeypatch.setattr(api_main, "now_utc", lambda: NOW + timedelta(minutes=2))
    latest = client.get(f"/api/v1/crew/{CREW}/latest").json()
    assert latest["assessment"]["overall_level"] is None


def test_rfid_state_survives_reload_and_ignores_old_replays(client):
    event = example("event-crew_checkin.example.json")
    client.post("/api/v1/events", json=event, headers=AUTH)
    assert client.get("/api/v1/crew/active").json()["crew_id"] == CREW
    old = example("telemetry.example.json", ts=stamp(NOW - timedelta(seconds=5)), crew_id="336F8312")
    client.post("/api/v1/telemetry", json=old, headers=AUTH)
    assert client.get("/api/v1/crew/active").json()["crew_id"] == CREW


def test_cors_allows_separate_frontend(client):
    response = client.options("/api/v1/checks", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == "*"
