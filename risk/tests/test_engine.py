import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk import evaluate

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SYSTEMS = {"cardiovascular", "neuro", "musculoskeletal", "environment"}
NOW = datetime(2026, 11, 14, 10, 30, 5, tzinfo=timezone.utc)


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def telemetry(**changes) -> dict:
    """Telemetría de ejemplo con campos cambiados: telemetry(vitals={"heart_rate_bpm": 125})."""
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


# --- forma del contrato ----------------------------------------------------------

def test_devuelve_la_forma_del_contrato():
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)

    assert result["crew_id"] == "F3786E09"
    assert result["ts"] == "2026-11-14T10:30:05Z"
    assert set(result["systems"]) == SYSTEMS
    for system in result["systems"].values():
        assert system["level"] in (None, 0, 1, 2, 3)
        assert all(isinstance(r, str) for r in system["reasons"])
    assert result["trends"] == []
    assert isinstance(result["recommendations"], list)


def test_ejemplos_del_contrato_salen_en_verde():
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)
    assert result["overall_level"] == 0
    assert result["recommendations"] == []
    for name in ("cardiovascular", "neuro", "environment"):
        assert result["systems"][name] == {"level": 0, "reasons": []}


def test_sin_datos_no_es_verde():
    result = evaluate([], [], [], NOW)
    assert result["crew_id"] is None
    assert result["overall_level"] is None
    assert result["systems"]["cardiovascular"]["level"] is None
    assert "Pulso: sin dato" in result["systems"]["cardiovascular"]["reasons"]


def test_telemetria_sin_datos_del_contrato():
    msg = load("telemetry-no-data.example.json")
    msg["ts"] = "2026-11-14T10:30:00Z"
    result = evaluate([msg], [], [], NOW)
    env = result["systems"]["environment"]
    assert env["level"] is None
    assert "Humedad de cabina: sin dato" in env["reasons"]


# --- niveles ------------------------------------------------------------------------

def test_pulso_alto_es_ambar_y_explica_por_que():
    result = evaluate([telemetry(vitals={"heart_rate_bpm": 118})], [], [check()], NOW)
    cardio = result["systems"]["cardiovascular"]
    assert cardio["level"] == 1
    assert cardio["reasons"] == ["Pulso 118 lat/min, por encima de 100 lat/min"]
    assert result["overall_level"] == 1
    assert result["recommendations"] == ["Reposo sentado 10 minutos y repetir la medida de pulso"]


def test_el_sistema_toma_el_peor_indicador():
    msg = telemetry(vitals={"heart_rate_bpm": 118, "body_temp_c": 38.3})
    cardio = evaluate([msg], [], [check()], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 2
    assert cardio["reasons"][0].startswith("Temperatura corporal 38,3")


def test_nivel_2_avisa_al_oficial_medico():
    result = evaluate([telemetry(cabin={"humidity_pct": 80})], [], [check()], NOW)
    assert result["systems"]["environment"]["level"] == 2
    assert result["recommendations"][0] == "Avisar al oficial médico de la tripulación"


def test_usa_el_ultimo_dato_valido():
    old = telemetry(vitals={"heart_rate_bpm": 130})
    old["ts"] = "2026-11-14T10:29:55Z"
    new = telemetry(vitals={"heart_rate_bpm": None})
    result = evaluate([new, old], [], [check()], NOW)   # desordenados a propósito
    assert result["systems"]["cardiovascular"]["level"] == 2


def test_telemetria_vieja_es_sin_dato():
    stale = telemetry(vitals={"heart_rate_bpm": 130})
    stale["ts"] = "2026-11-14T10:20:00Z"
    cardio = evaluate([stale], [], [check()], NOW)["systems"]["cardiovascular"]
    assert "Pulso: sin dato" in cardio["reasons"]


def test_condensacion_por_margen_sobre_rocio():
    msg = telemetry(cabin={"temp_c": 20.0, "dew_point_c": 18.5})
    env = evaluate([msg], [], [check()], NOW)["systems"]["environment"]
    assert env["level"] == 2
    assert any(r.startswith("Margen sobre el punto de rocío 1,5") for r in env["reasons"])


# --- chequeo manual -------------------------------------------------------------------

def test_tension_alta_una_sola_vez_se_queda_en_ambar():
    c = check(blood_pressure={"systolic": 145, "diastolic": 85})
    cardio = evaluate([telemetry()], [], [c], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 1
    assert "se confirma con una segunda" in cardio["reasons"][0]


def test_tension_alta_dos_veces_es_naranja():
    first = check("2026-11-14T07:55:00Z", blood_pressure={"systolic": 145, "diastolic": 85})
    second = check(blood_pressure={"systolic": 142, "diastolic": 85})
    cardio = evaluate([telemetry()], [], [first, second], NOW)["systems"]["cardiovascular"]
    assert cardio["level"] == 2


def test_tension_muy_alta_es_roja_con_una_medida():
    c = check(blood_pressure={"systolic": 185, "diastolic": 100})
    result = evaluate([telemetry()], [], [c], NOW)
    assert result["systems"]["cardiovascular"]["level"] == 3
    assert result["recommendations"][0] == "Contactar con los médicos en Tierra"


def test_animo_bajo_sube_neuro():
    neuro = evaluate([telemetry()], [], [check(mood=1)], NOW)["systems"]["neuro"]
    assert neuro["level"] == 2


# --- flexiones ------------------------------------------------------------------------

def test_flexiones_sin_basal_no_se_evaluan():
    musc = evaluate([telemetry()], [pushups(12, 5)], [check()], NOW)["systems"]["musculoskeletal"]
    assert not any("flexiones" in r for r in musc["reasons"])


def test_caida_de_flexiones_bajo_el_80_por_ciento_es_naranja():
    events = [pushups(20, 60 * 24), pushups(20, 60 * 12), pushups(14, 5)]   # 30 % menos
    musc = evaluate([telemetry()], events, [check()], NOW)["systems"]["musculoskeletal"]
    assert musc["level"] == 2
    assert musc["reasons"][0].startswith("Caída de flexiones respecto a su media 30")


def test_nunca_lanza_excepciones_con_basura():
    junk = [{}, {"ts": "no es fecha"}, {"ts": "2026-11-14T10:30:00Z", "vitals": None, "cabin": None}]
    result = evaluate(junk, junk, junk, NOW)
    assert set(result["systems"]) == SYSTEMS


def test_mismas_claves_que_el_ejemplo_del_contrato():
    example = load("assessment.example.json")
    result = evaluate([load("telemetry.example.json")], [], [load("check.example.json")], NOW)
    assert set(result) == set(example)
    assert set(example["trends"][0]) == {
        "indicator", "projected_7d", "crosses_threshold_in_days",
        "threshold", "threshold_level", "slope_per_day",
    }
