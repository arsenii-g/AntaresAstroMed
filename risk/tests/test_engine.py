import copy
import json

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk import evaluate

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SYSTEMS = {"cardiovascular", "neuro", "musculoskeletal", "environment"}
NOW = datetime(2026, 11, 14, 10, 30, 5, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def telemetry(**changes) -> dict:
    """Example telemetry with changed fields: telemetry(vitals={"heart_rate_bpm": 125})."""
    msg = copy.deepcopy(load("telemetry.example.json"))
    for block, values in changes.items():
        if isinstance(values, dict):
            msg[block].update(values)
        else:
            msg[block] = values
    return msg


def check(ts: str = "2026-11-14T08:00:00Z", **values) -> dict:
    msg = copy.deepcopy(load("check.example.json"))
    msg["ts"] = ts
    msg.update(values)
    return msg


def pushups(reps: int, minutes_ago: int) -> dict:
    ev = copy.deepcopy(load("event.example.json"))
    ev["ts"] = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ev["data"]["reps"] = reps
    return ev


# --- contract shape ----------------------------------------------------------

def test_returns_the_contract_shape():
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)

    assert result["crew_id"] == "F3786E09"
    assert result["ts"] == "2026-11-14T10:30:05Z"
    assert set(result["systems"]) == SYSTEMS
    for system in result["systems"].values():
        assert system["level"] in (None, 0, 1, 2, 3)
        assert all(isinstance(r, str) for r in system["reasons"])
    assert result["trends"] == []
    assert isinstance(result["recommendations"], list)


def test_contract_examples_come_out_green():
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)
    assert result["overall_level"] == 0
    assert result["recommendations"] == []
    for name in ("cardiovascular", "neuro", "environment"):
        assert result["systems"][name] == {"level": 0, "reasons": []}


def test_no_data_is_not_green():
    result = evaluate([], [], [], NOW)
    assert result["crew_id"] is None
    assert result["overall_level"] is None
    assert result["systems"]["cardiovascular"]["level"] is None
    assert "Heart rate: no data" in result["systems"]["cardiovascular"]["reasons"]


def test_contract_telemetry_without_data():
    msg = load("telemetry-no-data.example.json")
    msg["ts"] = "2026-11-14T10:30:00Z"
    result = evaluate([msg], [], [], NOW)
    env = result["systems"]["environment"]
    assert env["level"] is None
    assert "Cabin humidity: no data" in env["reasons"]


# --- levels ------------------------------------------------------------------------

def test_high_pulse_is_amber_and_explains_why():
    result = evaluate([telemetry(vitals={"heart_rate_bpm": 118})], [], [check()], NOW)
    cardio = result["systems"]["cardiovascular"]
    assert cardio["level"] == 1
    assert cardio["reasons"] == ["Heart rate 118 bpm, above 100 bpm"]
    assert result["overall_level"] == 1
    assert result["recommendations"] == ["Seated rest for 10 minutes, then repeat the heart rate reading"]


def test_system_takes_the_worst_indicator():
    msgs = hr_series(118, 118, 118)
    for m in msgs:
        m["vitals"]["body_temp_c"] = 38.3
    cardio = evaluate(msgs, [], [check()], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 2
    assert cardio["reasons"][0].startswith("Body temperature 38.3")


def test_level_2_notifies_the_medical_officer():
    result = evaluate([telemetry(cabin={"humidity_pct": 80})], [], [check()], NOW)
    assert result["systems"]["environment"]["level"] == 2
    assert result["recommendations"][0] == "Notify the crew medical officer"


def hr_series(*values, start=NOW - timedelta(seconds=5 * 10), activity="still"):
    """Telemetry every 5 s with these pulses; the last one arrives at `start + 5*(n-1)`."""
    msgs = []
    for i, hr in enumerate(values):
        m = telemetry(vitals={"heart_rate_bpm": hr})
        m["ts"] = (start + timedelta(seconds=5 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        m.setdefault("motion", {})["activity"] = activity
        msgs.append(m)
    return msgs


def test_uses_the_last_valid_reading():
    *older, last = hr_series(130, 130, 130, None)
    result = evaluate([last] + older[::-1], [], [check()], NOW)   # deliberately out of order
    assert result["systems"]["cardiovascular"]["level"] == 2


def test_isolated_high_pulse_does_not_escalate_until_sustained():
    cardio = lambda msgs: evaluate(msgs, [], [check()], NOW)["systems"]["cardiovascular"]
    one = cardio(hr_series(155))
    assert one["level"] == 1 and "not sustained yet: 1 of 3 readings" in one["reasons"][0]
    spike = cardio(hr_series(80, 80, 190))                   # a spike: amber, never green
    assert spike["level"] == 1 and "not sustained yet: 1 of 3 readings" in spike["reasons"][0]
    noisy = cardio(hr_series(160, 160, 95))                  # a low glitch does not hide a 160
    assert noisy["level"] == 1 and "2 of 3" in noisy["reasons"][0]
    assert cardio(hr_series(80, 80, 80))["level"] == 0
    flipped = cardio(hr_series(190, 40, 190))                # high and low mixed
    assert flipped["level"] == 1 and "check the sensor" in flipped["reasons"][0]
    assert "above" in flipped["reasons"][0]
    sustained = cardio(hr_series(155, 156, 158))
    assert sustained["level"] == 3 and "sustained over 3 readings" in sustained["reasons"][0]
    mixed = cardio(hr_series(155, 125, 158))                 # the least severe one wins
    assert mixed["level"] == 2


def test_high_pulse_after_push_ups_or_while_moving_drops_one_level():
    cardio = lambda msgs, ev=(): evaluate(msgs, list(ev), [check()], NOW)["systems"]["cardiovascular"]
    moving = cardio(hr_series(125, 126, 128, activity="moving"))
    assert moving["level"] == 1 and "after exercise; recheck at rest" in moving["reasons"][0]
    assert cardio(hr_series(155, 156, 158, activity="moving"))["level"] == 3   # red is not downgraded
    set_now = copy.deepcopy(load("event.example.json"))
    set_now["ts"] = (NOW - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert cardio(hr_series(125, 126, 128), [set_now])["level"] == 1
    set_old = copy.deepcopy(set_now)
    set_old["ts"] = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert cardio(hr_series(125, 126, 128), [set_old])["level"] == 2
    low = cardio(hr_series(42, 42, 42, activity="moving"))  # a low pulse is not forgiven
    assert low["level"] == 2


def test_old_telemetry_is_no_data():
    stale = telemetry(vitals={"heart_rate_bpm": 130})
    stale["ts"] = "2026-11-14T10:20:00Z"
    cardio = evaluate([stale], [], [check()], NOW)["systems"]["cardiovascular"]
    assert "Heart rate: no data" in cardio["reasons"]


def test_condensation_by_margin_above_dew_point():
    msg = telemetry(cabin={"temp_c": 20.0, "dew_point_c": 18.5})
    env = evaluate([msg], [], [check()], NOW)["systems"]["environment"]
    assert env["level"] == 2
    assert any(r.startswith("Margin above dew point 1.5") for r in env["reasons"])


# --- manual check -------------------------------------------------------------------

def test_high_blood_pressure_once_stays_amber():
    c = check(blood_pressure={"systolic": 145, "diastolic": 85})
    cardio = evaluate([telemetry()], [], [c], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 1
    assert "confirm with a second one" in cardio["reasons"][0]


def test_high_blood_pressure_twice_is_orange():
    first = check("2026-11-14T07:55:00Z", blood_pressure={"systolic": 145, "diastolic": 85})
    second = check(blood_pressure={"systolic": 142, "diastolic": 85})
    cardio = evaluate([telemetry()], [], [first, second], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 2


def test_very_high_blood_pressure_is_red_with_one_reading():
    c = check(blood_pressure={"systolic": 185, "diastolic": 100})
    result = evaluate([telemetry()], [], [c], NOW)
    assert result["systems"]["cardiovascular"]["level"] == 3
    assert result["recommendations"][0] == "Contact the medical team on Earth"


def test_low_mood_raises_neuro():
    neuro = evaluate([telemetry()], [], [check(mood=1)], NOW)["systems"]["neuro"]
    assert neuro["level"] == 2


# --- push-ups ------------------------------------------------------------------------

def test_push_ups_without_baseline_are_not_evaluated():
    musc = evaluate([telemetry()], [pushups(12, 5)], [check()], NOW)["systems"]["musculoskeletal"]
    assert not any("Push-up" in r for r in musc["reasons"])


def test_push_up_drop_below_80_percent_is_orange():
    events = [pushups(20, 60 * 24), pushups(20, 60 * 12), pushups(14, 5)]   # 30 % fewer
    musc = evaluate([telemetry()], events, [check()], NOW)["systems"]["musculoskeletal"]
    assert musc["level"] == 2
    assert musc["reasons"][0].startswith("Push-up drop vs. own average 30%")


def test_never_raises_with_garbage():
    junk = [{}, {"ts": "no es fecha"}, {"ts": "2026-11-14T10:30:00Z", "vitals": None, "cabin": None}]
    result = evaluate(junk, junk, junk, NOW)
    assert set(result["systems"]) == SYSTEMS


def test_same_keys_as_the_contract_example():
    example = load("assessment.example.json")
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)
    assert set(result) == set(example)
    assert set(example["trends"][0]) == {
        "indicator", "label", "unit", "basis", "x_unit", "points", "slope", "intercept",
        "horizon", "projected", "threshold", "threshold_level", "crosses_in",
    }


def test_isolated_low_temperature_is_not_red():
    def temps(*values):
        msgs = hr_series(*[75] * len(values))
        for m, t in zip(msgs, values):
            m["vitals"]["body_temp_c"] = t
        return evaluate(msgs, [], [check()], NOW)
    loose = temps(36.6, 36.7, 34.8)                     # half-loose thermistor
    assert loose["systems"]["cardiovascular"]["level"] == 1 and loose["earth_summary"] is None
    cold = temps(34.8, 34.7, 34.6)                      # cold wrist: amber at most
    cardio = cold["systems"]["cardiovascular"]
    assert cardio["level"] == 1 and cold["earth_summary"] is None
    assert cardio["reasons"][0] == "Body temperature 34.6 °C, below 36 °C (wrist reading; confirm with a thermometer)"
    fever = temps(39.6, 39.7, 39.8)                     # fever does reach red
    assert fever["systems"]["cardiovascular"]["level"] == 3


def test_duplicates_count_once():
    msg = hr_series(155)[0]
    msg["device_id"] = "esp32-01"
    cardio = evaluate([msg, copy.deepcopy(msg), copy.deepcopy(msg)], [], [check()], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 1                          # a retry stored 3 times is not "sustained"
    c = check()
    c["blood_pressure"] = {"systolic": 145, "diastolic": 80}
    cardio = evaluate([], [], [c, copy.deepcopy(c)], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 1 and "first reading" in cardio["reasons"][0]


def test_garbage_does_not_raise():
    junk = [
        telemetry(vitals={"heart_rate_bpm": "80", "body_temp_c": True}, cabin={"temp_c": "x"}),
        {**telemetry(), "vitals": [1], "motion": "still", "cabin": None},
        "no soy un dict", None, 42,
    ]
    bad_checks = [{**check(), "mood": "3", "blood_pressure": [120, 80], "glucose_mg_dl": float("nan")}]
    bad_events = [{"type": "exercise_summary", "ts": "2026-11-14T10:00:00Z", "data": "20 reps"}]
    result = evaluate(junk, bad_events, bad_checks, NOW)
    assert set(result) == set(load("assessment.example.json"))
    assert "Heart rate: no data" in result["systems"]["cardiovascular"]["reasons"]
    assert evaluate("basura", None, {"a": 1}, NOW)["overall_level"] is None


def test_now_without_timezone_is_an_error():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate([], [], [], datetime(2026, 11, 14, 10, 30))


def test_previous_crew_members_set_does_not_count():
    def ev(kind, seconds_ago, data):
        e = copy.deepcopy(load("event.example.json"))
        e["type"], e["data"] = kind, data
        e["ts"] = (NOW - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return e
    usual = [ev("exercise_summary", 86400 * d, {"exercise": "pushup", "reps": 20}) for d in (3, 2, 1)]
    swap = [ev("crew_checkin", 60, {"action": "in"}), ev("exercise_summary", 59, {"exercise": "pushup", "reps": 4})]
    muscle = evaluate([], usual + swap, [check()], NOW)["systems"]["musculoskeletal"]
    assert muscle["level"] == 0                          # the 4 push-ups belonged to the previous person
    later = ev("exercise_summary", 10, {"exercise": "pushup", "reps": 4})
    assert evaluate([], usual + swap + [later], [check()], NOW)["systems"]["musculoskeletal"]["level"] >= 2
