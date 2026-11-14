import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from risk import evaluate


def test_two_second_firmware_still_needs_ten_seconds_of_sustained_pulse():
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    template = json.loads((Path(__file__).resolve().parents[2] / "contracts/telemetry.example.json").read_text())
    messages = []
    for i in range(6):
        msg = copy.deepcopy(template)
        msg["ts"] = (now - timedelta(seconds=10 - i * 2)).isoformat()
        msg["vitals"]["heart_rate_bpm"] = 156
        messages.append(msg)
    early = evaluate(messages[:3], [], [], now)["systems"]["cardiovascular"]
    assert early["level"] == 1
    confirmed = evaluate(messages, [], [], now)["systems"]["cardiovascular"]
    assert confirmed["level"] == 3
    assert "sustained over 6 readings" in confirmed["reasons"][0]
