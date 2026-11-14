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


def test_glucosa_que_sube_avisa_antes_de_salir_de_verde():
    checks = [day_check(d, glucose=80 + 3 * (6 - d)) for d in range(6, -1, -1)]   # 80 → 98
    result = evaluate([], [], checks, NOW)
    t = trend(result, "glucose_mg_dl")
    assert result["systems"]["cardiovascular"]["level"] == 0       # hoy sigue en verde
    assert t["slope_per_day"] == pytest.approx(3, abs=0.01)
    assert t["threshold"] == 99 and t["threshold_level"] == 1
    assert 0 < t["crosses_threshold_in_days"] <= 1
    assert any(r.startswith("Trend: glucose will reach 99 mg/dL") for r in result["recommendations"])


def test_valores_estables_no_cruzan():
    checks = [day_check(d) for d in range(6, -1, -1)]
    result = evaluate([], [], checks, NOW)
    assert {t["indicator"] for t in result["trends"]} == {"systolic_mmhg", "diastolic_mmhg", "glucose_mg_dl", "mood"}
    assert all(t["crosses_threshold_in_days"] is None for t in result["trends"])
    assert not any(r.startswith("Trend") for r in result["recommendations"])


def test_animo_que_baja_cruza_por_abajo_y_no_baja_de_1():
    checks = [day_check(d, mood=m) for d, m in zip(range(4, -1, -1), [5, 5, 4, 4, 3])]
    t = trend(evaluate([], [], checks, NOW), "mood")
    assert t["threshold"] == 3 and t["threshold_level"] == 1     # 3 aún es verde: el ámbar es menos de 3
    assert t["projected_7d"] >= 1


def test_flexiones_que_caen_cruzan_el_80_por_ciento():
    events = [pushups(d, r) for d, r in zip(range(6, -1, -1), [20, 20, 19, 19, 18, 18, 17])]
    result = evaluate([], events, [], NOW)
    t = trend(result, "pushup_reps")
    assert t["slope_per_day"] < 0
    assert t["threshold_level"] in (1, 2)
    assert t["crosses_threshold_in_days"] is not None


def test_pocos_datos_no_dan_tendencia():
    result = evaluate([], [], [day_check(1), day_check(0)], NOW)
    assert result["trends"] == []


def test_resumen_a_tierra_solo_en_rojo_y_en_ingles():
    green = evaluate([], [], [day_check(0)], NOW)
    assert green["earth_summary"] is None

    red = evaluate([], [], [day_check(0, systolic=185, diastolic=100)], NOW)
    text = red["earth_summary"]
    assert red["overall_level"] == 3
    assert text.startswith("SPACEHEALTH MEDICAL SUMMARY")
    assert "Crew member: F3786E09" in text
    assert "[red] Systolic blood pressure 185 mmHg, above 181 mmHg" in text
    assert "Rest for 5 minutes and repeat the blood pressure" in text


def test_modo_demo_baja_la_inactividad_a_30_s(monkeypatch):
    assert level_for("still_for_s", 45).level == 0
    monkeypatch.setenv("SPACEHEALTH_DEMO", "1")
    assert level_for("still_for_s", 45).level == 1
    assert level_for("still_for_s", 90).level == 2


def test_tension_se_confirma_con_la_medida_de_ayer():
    cardio = lambda checks: evaluate([], [], checks, NOW)["systems"]["cardiovascular"]
    first = cardio([day_check(0, systolic=145)])
    assert first["level"] == 1 and "first reading" in first["reasons"][0]
    confirmed = cardio([day_check(1, systolic=145), day_check(0, systolic=146)])   # ayer, a 25 h
    assert confirmed["level"] == 2
    only_yesterday = cardio([day_check(1, systolic=145)])                          # hoy no hay medida
    assert "Systolic blood pressure: no data" in only_yesterday["reasons"]


def test_animo_frente_a_su_propia_media():
    neuro = lambda checks: evaluate([], [], checks, NOW)["systems"]["neuro"]
    assert neuro([day_check(0, mood=3)])["level"] == 0                             # sin historia: corte fijo
    usual_5 = [day_check(d, mood=5) for d in (4, 3, 2, 1)] + [day_check(0, mood=3)]
    drop = neuro(usual_5)
    assert drop["level"] == 1 and "2 points below own average 5/5" in drop["reasons"][0]
    usual_4 = [day_check(d, mood=4) for d in (4, 3, 2, 1)] + [day_check(0, mood=3)]
    assert neuro(usual_4)["level"] == 0                                            # 1 punto: normal
    two_before = [day_check(d, mood=5) for d in (2, 1)] + [day_check(0, mood=3)]
    assert neuro(two_before)["level"] == 0                                         # pocos chequeos previos


def test_animo_baja_1_5_de_su_media():
    usual = [day_check(d, mood=m) for d, m in zip((3, 2, 1), (5, 5, 4))] + [day_check(0, mood=3)]
    neuro = evaluate([], [], usual, NOW)["systems"]["neuro"]
    assert neuro["level"] == 1 and "below own average" in neuro["reasons"][0]
