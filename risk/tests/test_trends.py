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


def test_glucosa_que_sube_avisa_antes_de_salir_de_verde():
    checks = [day_check(d, glucose=80 + 3 * (6 - d)) for d in range(6, -1, -1)]   # 80 → 98
    result = evaluate([], [], checks, NOW)
    t = trend(result, "glucose_mg_dl")
    assert result["systems"]["cardiovascular"]["level"] == 0       # hoy sigue en verde
    assert t["basis"] == "count" and t["x_unit"] == "check"
    assert t["slope"] == pytest.approx(3, abs=0.01)                # 3 mg/dL por chequeo
    assert t["threshold"] == 99 and t["threshold_level"] == 1
    assert 0 < t["crosses_in"] <= 1
    assert t["points"] == [[-6.0, 80.0], [-5.0, 83.0], [-4.0, 86.0], [-3.0, 89.0], [-2.0, 92.0], [-1.0, 95.0], [0.0, 98.0]]
    assert any(r.startswith("Trend: glucose will reach 99 mg/dL in about 1 more daily check") for r in result["recommendations"])


def test_siete_chequeos_seguidos_dan_la_misma_recta_que_siete_dias():
    """En la demo se meten 7 chequeos en unos minutos: la recta va por chequeo, no por día."""
    by_day = trend(evaluate([], [], [day_check(d, glucose=80 + 3 * (6 - d)) for d in range(6, -1, -1)], NOW), "glucose_mg_dl")
    quick = [minutes_check(6 - i, glucose=80 + 3 * i) for i in range(7)]
    fast = trend(evaluate([], [], quick, NOW), "glucose_mg_dl")
    for key in ("slope", "intercept", "projected", "threshold", "crosses_in", "points"):
        assert fast[key] == by_day[key]


def test_hacen_falta_7_medidas():
    six = [minutes_check(5 - i, glucose=90 + i) for i in range(6)]
    assert evaluate([], [], six, NOW)["trends"] == []
    seven = [minutes_check(6 - i, glucose=90 + i) for i in range(7)]
    names = {t["indicator"] for t in evaluate([], [], seven, NOW)["trends"]}
    assert names == {"systolic_mmhg", "diastolic_mmhg", "glucose_mg_dl", "mood"}


def test_valores_estables_no_cruzan():
    checks = [day_check(d) for d in range(6, -1, -1)]
    result = evaluate([], [], checks, NOW)
    assert all(t["crosses_in"] is None for t in result["trends"])
    assert not any(r.startswith("Trend") for r in result["recommendations"])


def test_recta_cuenta_aunque_falte_un_dato_en_algun_chequeo():
    checks = [minutes_check(7 - i, glucose=90 + i) for i in range(8)]
    checks[3]["glucose_mg_dl"] = None                               # ese día no se midió
    t = trend(evaluate([], [], checks, NOW), "glucose_mg_dl")
    assert len(t["points"]) == 7 and t["points"][-1] == [0.0, 97.0]


def test_animo_que_baja_cruza_por_abajo_y_no_baja_de_1():
    moods = [5, 5, 5, 4, 4, 4, 3]
    checks = [minutes_check(6 - i, mood=m) for i, m in enumerate(moods)]
    t = trend(evaluate([], [], checks, NOW), "mood")
    assert t["threshold"] == 3 and t["threshold_level"] == 1     # 3 aún es verde: el ámbar es menos de 3
    assert t["slope"] < 0 and t["projected"] >= 1


def test_flexiones_que_caen_cruzan_el_umbral_de_la_basal():
    events = [pushups(d, r) for d, r in zip(range(6, -1, -1), [20, 20, 19, 19, 18, 18, 17])]
    result = evaluate([], events, [], NOW)
    t = trend(result, "pushup_reps")
    assert t["x_unit"] == "set" and t["slope"] < 0
    assert t["threshold_level"] in (1, 2)
    assert t["crosses_in"] is not None


def test_pulso_que_sube_en_el_ultimo_minuto_da_tendencia_en_segundos():
    msgs = [telemetry(2 * (14 - i), hr=80 + 2 * i) for i in range(15)]       # 80 → 108 en 28 s
    t = trend(evaluate(msgs, [], [], NOW), "heart_rate_bpm")
    assert t["basis"] == "time" and t["x_unit"] == "s" and t["horizon"] == 60
    assert t["slope"] == pytest.approx(1.0)                                  # 1 lpm por segundo
    assert t["threshold"] == 120 and t["threshold_level"] == 2
    assert t["crosses_in"] == pytest.approx(12, abs=0.1)
    assert t["points"][-1] == [0.0, 108.0]


def test_sensor_sin_datos_no_da_tendencia_y_menos_de_7_lecturas_tampoco():
    assert evaluate([telemetry(2 * (5 - i), hr=70) for i in range(6)], [], [], NOW)["trends"] == []
    msgs = [telemetry(2 * (9 - i), cabin=23.0 + 0.1 * i, rh=45) for i in range(10)]
    names = {t["indicator"] for t in evaluate(msgs, [], [], NOW)["trends"]}
    assert names == {"cabin_temp_c", "humidity_pct"}


def test_temperatura_corporal_que_baja_solo_vigila_el_ambar():
    msgs = [telemetry(2 * (9 - i), temp=37.2 - 0.05 * i) for i in range(10)]   # 37.2 → 36.75
    t = trend(evaluate(msgs, [], [], NOW), "body_temp_c")
    assert t["threshold"] == 36.0 and t["threshold_level"] == 1
    later = [telemetry(2 * (9 - i), temp=35.9 - 0.1 * i) for i in range(10)]
    assert trend(evaluate(later, [], [], NOW), "body_temp_c")["threshold"] is None


def test_pocos_datos_no_dan_tendencia():
    result = evaluate([], [], [day_check(1), day_check(0)], NOW)
    assert result["trends"] == []


def test_resumen_a_tierra_solo_en_rojo_y_en_ingles():
    green = evaluate([], [], [day_check(0)], NOW)
    assert green["earth_summary"] is None

    red = evaluate([], [], [day_check(0, systolic=185, diastolic=100)], NOW)
    text = red["earth_summary"]
    assert red["overall_level"] == 3
    assert text.startswith("ASTROMED MEDICAL SUMMARY")
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


def test_si_la_recta_va_hacia_lo_normal_no_hay_umbral():
    falling_high = [telemetry(2 * (9 - i), hr=160 - i) for i in range(10)]   # rojo que baja: se recupera
    t = trend(evaluate(falling_high, [], [], NOW), "heart_rate_bpm")
    assert t["slope"] < 0 and t["threshold"] is None and t["crosses_in"] is None
    rising_low = [telemetry(2 * (9 - i), cabin=23, rh=20 + i) for i in range(10)]   # humedad baja que sube
    assert trend(evaluate(rising_low, [], [], NOW), "humidity_pct")["threshold"] is None
    rising_high = [telemetry(2 * (9 - i), hr=130 + i) for i in range(10)]    # naranja que sube: vigila el rojo
    assert trend(evaluate(rising_high, [], [], NOW), "heart_rate_bpm")["threshold"] == 150
