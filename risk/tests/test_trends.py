import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from risk import evaluate
from risk.indicators import level_for

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
NOW = datetime(2026, 11, 14, 10, 30, 5, tzinfo=timezone.utc)


def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def day_check(days_ago, systolic=118, diastolic=76, glucose=92, mood=4):
    c = copy.deepcopy(load("check.example.json"))
    c["ts"] = (NOW - timedelta(days=days_ago, hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    c["blood_pressure"] = {"systolic": systolic, "diastolic": diastolic}
    c["glucose_mg_dl"], c["mood"] = glucose, mood
    return c


def pushups(days_ago, reps):
    e = copy.deepcopy(load("event.example.json"))
    e["ts"] = (NOW - timedelta(days=days_ago, hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    e["data"]["reps"] = reps
    return e


def trend(result, indicator):
    return next(t for t in result["trends"] if t["indicator"] == indicator)


def minutes_check(minutes_ago, **values):
    c = day_check(0, **values)
    c["ts"] = (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return c


def telemetry(seconds_ago, hr=None, temp=None, cabin=None, rh=None):
    m = copy.deepcopy(load("telemetry.example.json"))
    m["ts"] = (NOW - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    m["vitals"]["heart_rate_bpm"], m["vitals"]["body_temp_c"] = hr, temp
    m["cabin"]["temp_c"], m["cabin"]["humidity_pct"] = cabin, rh
    return m


def test_rising_glucose_warns_before_leaving_green():
    checks = [day_check(d, glucose=80 + 3 * (6 - d)) for d in range(6, -1, -1)]   # 80 -> 98
    result = evaluate([], [], checks, NOW)
    t = trend(result, "glucose_mg_dl")
    assert result["systems"]["cardiovascular"]["level"] == 0       # still green today
    assert t["basis"] == "count" and t["x_unit"] == "check"
    assert t["slope"] == pytest.approx(3, abs=0.01)                # 3 mg/dL per check
    assert t["threshold"] == 99 and t["threshold_level"] == 1
    assert 0 < t["crosses_in"] <= 1
    assert t["points"] == [[-6.0, 80.0], [-5.0, 83.0], [-4.0, 86.0], [-3.0, 89.0], [-2.0, 92.0], [-1.0, 95.0], [0.0, 98.0]]
    assert any(r.startswith("Trend: glucose will reach 99 mg/dL in about 1 more daily check") for r in result["recommendations"])


def test_seven_consecutive_checks_give_the_same_line_as_seven_days():
    """In the demo, 7 checks are entered within a few minutes: the line goes per check, not per day."""
    by_day = trend(evaluate([], [], [day_check(d, glucose=80 + 3 * (6 - d)) for d in range(6, -1, -1)], NOW), "glucose_mg_dl")
    quick = [minutes_check(6 - i, glucose=80 + 3 * i) for i in range(7)]
    fast = trend(evaluate([], [], quick, NOW), "glucose_mg_dl")
    for key in ("slope", "intercept", "projected", "threshold", "crosses_in", "points"):
        assert fast[key] == by_day[key]


def test_seven_measurements_are_needed():
    six = [minutes_check(5 - i, glucose=90 + i) for i in range(6)]
    assert evaluate([], [], six, NOW)["trends"] == []
    seven = [minutes_check(6 - i, glucose=90 + i) for i in range(7)]
    names = {t["indicator"] for t in evaluate([], [], seven, NOW)["trends"]}
    assert names == {"systolic_mmhg", "diastolic_mmhg", "glucose_mg_dl", "mood"}


def test_stable_values_do_not_cross():
    checks = [day_check(d) for d in range(6, -1, -1)]
    result = evaluate([], [], checks, NOW)
    assert all(t["crosses_in"] is None for t in result["trends"])
    assert not any(r.startswith("Trend") for r in result["recommendations"])


def test_line_counts_even_if_a_check_is_missing_a_value():
    checks = [minutes_check(7 - i, glucose=90 + i) for i in range(8)]
    checks[3]["glucose_mg_dl"] = None                               # not measured that day
    t = trend(evaluate([], [], checks, NOW), "glucose_mg_dl")
    assert len(t["points"]) == 7 and t["points"][-1] == [0.0, 97.0]


def test_falling_mood_crosses_downward_and_stays_at_or_above_1():
    moods = [5, 5, 5, 4, 4, 4, 3]
    checks = [minutes_check(6 - i, mood=m) for i, m in enumerate(moods)]
    t = trend(evaluate([], [], checks, NOW), "mood")
    assert t["threshold"] == 3 and t["threshold_level"] == 1     # 3 is still green: amber is below 3
    assert t["slope"] < 0 and t["projected"] >= 1


def test_falling_push_ups_cross_the_baseline_threshold():
    events = [pushups(d, r) for d, r in zip(range(6, -1, -1), [20, 20, 19, 19, 18, 18, 17])]
    result = evaluate([], events, [], NOW)
    t = trend(result, "pushup_reps")
    assert t["x_unit"] == "set" and t["slope"] < 0
    assert t["threshold_level"] in (1, 2)
    assert t["crosses_in"] is not None


def test_pulse_rising_in_the_last_minute_gives_a_trend_in_seconds():
    msgs = [telemetry(2 * (14 - i), hr=80 + 2 * i) for i in range(15)]       # 80 -> 108 in 28 s
    t = trend(evaluate(msgs, [], [], NOW), "heart_rate_bpm")
    assert t["basis"] == "time" and t["x_unit"] == "s" and t["horizon"] == 60
    assert t["slope"] == pytest.approx(1.0)                                  # 1 bpm per second
    assert t["threshold"] == 120 and t["threshold_level"] == 2
    assert t["crosses_in"] == pytest.approx(12, abs=0.1)
    assert t["points"][-1] == [0.0, 108.0]


def test_sensor_without_data_gives_no_trend_and_neither_do_fewer_than_7_readings():
    assert evaluate([telemetry(2 * (5 - i), hr=70) for i in range(6)], [], [], NOW)["trends"] == []
    msgs = [telemetry(2 * (9 - i), cabin=23.0 + 0.1 * i, rh=45) for i in range(10)]
    names = {t["indicator"] for t in evaluate(msgs, [], [], NOW)["trends"]}
    assert names == {"cabin_temp_c", "humidity_pct"}


def test_falling_body_temperature_only_monitors_amber():
    msgs = [telemetry(2 * (9 - i), temp=37.2 - 0.05 * i) for i in range(10)]   # 37.2 -> 36.75
    t = trend(evaluate(msgs, [], [], NOW), "body_temp_c")
    assert t["threshold"] == 36.0 and t["threshold_level"] == 1
    later = [telemetry(2 * (9 - i), temp=35.9 - 0.1 * i) for i in range(10)]
    assert trend(evaluate(later, [], [], NOW), "body_temp_c")["threshold"] is None


def test_few_data_points_give_no_trend():
    result = evaluate([], [], [day_check(1), day_check(0)], NOW)
    assert result["trends"] == []


def test_earth_summary_only_at_red_and_in_english():
    green = evaluate([], [], [day_check(0)], NOW)
    assert green["earth_summary"] is None

    red = evaluate([], [], [day_check(0, systolic=185, diastolic=100)], NOW)
    text = red["earth_summary"]
    assert red["overall_level"] == 3
    assert text.startswith("ASTROMED MEDICAL SUMMARY")
    assert "Crew member: F3786E09" in text
    assert "[red] Systolic blood pressure 185 mmHg, above 181 mmHg" in text
    assert "Rest for 5 minutes and repeat the blood pressure" in text


def test_demo_mode_lowers_inactivity_to_30_s(monkeypatch):
    assert level_for("still_for_s", 45).level == 0
    monkeypatch.setenv("SPACEHEALTH_DEMO", "1")
    assert level_for("still_for_s", 45).level == 1
    assert level_for("still_for_s", 90).level == 2


def test_blood_pressure_is_confirmed_by_yesterdays_reading():
    cardio = lambda checks: evaluate([], [], checks, NOW)["systems"]["cardiovascular"]
    first = cardio([day_check(0, systolic=145)])
    assert first["level"] == 1 and "first reading" in first["reasons"][0]
    confirmed = cardio([day_check(1, systolic=145), day_check(0, systolic=146)])   # yesterday, 25 h ago
    assert confirmed["level"] == 2
    only_yesterday = cardio([day_check(1, systolic=145)])                          # no reading today
    assert "Systolic blood pressure: no data" in only_yesterday["reasons"]


def test_mood_against_own_average():
    neuro = lambda checks: evaluate([], [], checks, NOW)["systems"]["neuro"]
    assert neuro([day_check(0, mood=3)])["level"] == 0                             # no history: fixed cut
    usual_5 = [day_check(d, mood=5) for d in (4, 3, 2, 1)] + [day_check(0, mood=3)]
    drop = neuro(usual_5)
    assert drop["level"] == 1 and "2 points below own average 5/5" in drop["reasons"][0]
    usual_4 = [day_check(d, mood=4) for d in (4, 3, 2, 1)] + [day_check(0, mood=3)]
    assert neuro(usual_4)["level"] == 0                                            # 1 point: normal
    two_before = [day_check(d, mood=5) for d in (2, 1)] + [day_check(0, mood=3)]
    assert neuro(two_before)["level"] == 0                                         # too few previous checks


def test_mood_1_5_below_own_average():
    usual = [day_check(d, mood=m) for d, m in zip((3, 2, 1), (5, 5, 4))] + [day_check(0, mood=3)]
    neuro = evaluate([], [], usual, NOW)["systems"]["neuro"]
    assert neuro["level"] == 1 and "below own average" in neuro["reasons"][0]


def test_if_the_line_heads_to_normal_there_is_no_threshold():
    falling_high = [telemetry(2 * (9 - i), hr=160 - i) for i in range(10)]   # red that falls: recovering
    t = trend(evaluate(falling_high, [], [], NOW), "heart_rate_bpm")
    assert t["slope"] < 0 and t["threshold"] is None and t["crosses_in"] is None
    rising_low = [telemetry(2 * (9 - i), cabin=23, rh=20 + i) for i in range(10)]   # low humidity that rises
    assert trend(evaluate(rising_low, [], [], NOW), "humidity_pct")["threshold"] is None
    rising_high = [telemetry(2 * (9 - i), hr=130 + i) for i in range(10)]    # orange that rises: watches red
    assert trend(evaluate(rising_high, [], [], NOW), "heart_rate_bpm")["threshold"] == 150
