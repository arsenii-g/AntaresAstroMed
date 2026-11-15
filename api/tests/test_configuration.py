import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from astromed_config import database_url
from risk.indicators import level_for


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for prefix in ("ASTROMED", "SPACEHEALTH"):
        for name in ("DEMO", "API_KEY", "DATABASE_URL", "CORS_ORIGINS"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)


@pytest.mark.parametrize("prefix", ["ASTROMED", "SPACEHEALTH"])
def test_current_and_existing_device_configuration_remain_usable(prefix, monkeypatch):
    monkeypatch.setenv(f"{prefix}_DATABASE_URL", "sqlite://")
    monkeypatch.setenv(f"{prefix}_API_KEY", "configured-key")
    monkeypatch.setenv(f"{prefix}_DEMO", "1")
    monkeypatch.setenv(f"{prefix}_CORS_ORIGINS", "https://crew.example")
    message = json.loads((Path(__file__).resolve().parents[2] / "contracts/telemetry.example.json").read_text())
    message["ts"] = datetime.now(timezone.utc).isoformat()
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/status").json()["demo_mode"] is True
        assert level_for("still_for_s", 45).level == 1
        reply = client.post("/api/v1/telemetry", json=message, headers={"X-API-Key": "configured-key"})
        assert reply.status_code == 200 and reply.json()["ok"] is True
        assert client.get("/api/v1/status", headers={"Origin": "https://crew.example"}).headers["access-control-allow-origin"] == "https://crew.example"


def test_astromed_settings_take_precedence_in_api_and_rules(monkeypatch):
    monkeypatch.setenv("SPACEHEALTH_DATABASE_URL", "invalid-legacy-url")
    monkeypatch.setenv("ASTROMED_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SPACEHEALTH_API_KEY", "old-key")
    monkeypatch.setenv("ASTROMED_API_KEY", "new-key")
    monkeypatch.setenv("SPACEHEALTH_DEMO", "1")
    monkeypatch.setenv("ASTROMED_DEMO", "0")
    monkeypatch.setenv("SPACEHEALTH_CORS_ORIGINS", "https://old.example")
    monkeypatch.setenv("ASTROMED_CORS_ORIGINS", "https://crew.example")
    with TestClient(create_app()) as client:
        status = client.get("/api/v1/status").json()
        assert status["demo_mode"] is False
        assert level_for("still_for_s", 45).level == 0
        assert client.post("/api/v1/events", json={}, headers={"X-API-Key": "old-key"}).status_code == 401
        assert client.post("/api/v1/events", json={}, headers={"X-API-Key": "new-key"}).status_code == 422
        assert "access-control-allow-origin" not in client.get("/api/v1/status", headers={"Origin": "https://old.example"}).headers
        assert client.get("/api/v1/status", headers={"Origin": "https://crew.example"}).headers["access-control-allow-origin"] == "https://crew.example"


def test_database_selection_preserves_recordings_and_honors_explicit_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert database_url() == "sqlite:///./astromed.db"
    legacy = tmp_path / "spacehealth.db"
    legacy.write_bytes(b"existing sensor data")
    assert database_url() == "sqlite:///./spacehealth.db"
    monkeypatch.setenv("ASTROMED_DATABASE_URL", "sqlite:///./recording.db")
    assert database_url() == "sqlite:///./recording.db"
    assert legacy.read_bytes() == b"existing sensor data"
