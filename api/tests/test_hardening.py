"""Regression tests for the final review fixes."""
from datetime import datetime, timezone

from api.models import RejectedMessage
from api.tests.test_api import AUTH, client, count, example  # noqa: F401  (fixture reuse)
from astromed_config import setting
from risk.engine import evaluate


def test_out_of_range_timestamp_is_rejected_not_a_server_error(client):
    for ts in ("0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00"):
        assert client.post("/api/v1/checks", json={"crew_id": "A", "ts": ts}).status_code == 422
        msg = example("telemetry.example.json", ts=ts)
        assert client.post("/api/v1/telemetry", json=msg, headers=AUTH).status_code == 422


def test_engine_ignores_out_of_range_timestamps():
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    bad = [{"crew_id": "A", "ts": "0001-01-01T00:00:00+05:00"}]
    assert evaluate(bad, bad, bad, now)["overall_level"] is None


def test_public_checks_route_does_not_store_rejections(client):
    assert client.post("/api/v1/checks", json={"crew_id": "A"}).status_code == 422
    assert count(client, RejectedMessage) == 0


def test_empty_variable_counts_as_unset(monkeypatch):
    monkeypatch.setenv("ASTROMED_DEMO", "")
    monkeypatch.setenv("SPACEHEALTH_DEMO", "1")
    assert setting("DEMO") == "1"
    monkeypatch.setenv("ASTROMED_DEMO", "0")
    assert setting("DEMO") == "0"
