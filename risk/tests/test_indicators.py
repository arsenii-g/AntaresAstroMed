import pytest

from risk.indicators import level_for, load_thresholds

SYSTEMS = {"cardiovascular", "neuro", "musculoskeletal", "environment"}


# --- el archivo de umbrales está bien formado -------------------------------

@pytest.mark.parametrize("name,spec", load_thresholds().items())
def test_umbrales_bien_formados(name, spec):
    assert spec["system"] in SYSTEMS
    for key in ("label", "unit", "code", "source"):
        assert spec[key], f"{name}: falta {key}"
    for side in ("high", "low"):
        cuts = spec.get(side, [])
        assert len(cuts) == 3, f"{name}.{side} debe tener 3 cortes"
        used = [c for c in cuts if c is not None]
        if side == "high":
            assert used == sorted(used), f"{name}.high debe ir de menor a mayor"
        else:
            assert used == sorted(used, reverse=True), f"{name}.low debe ir de mayor a menor"
    assert any(c is not None for c in spec["high"] + spec["low"]), f"{name} no tiene cortes"


# --- niveles ----------------------------------------------------------------

@pytest.mark.parametrize("indicator,value,level", [
    ("heart_rate_bpm", 72, 0),
    ("heart_rate_bpm", 100, 0),       # el corte no se incluye: hace falta pasar de 100
    ("heart_rate_bpm", 118, 1),
    ("heart_rate_bpm", 125, 2),       # guía: más de 120 → naranja
    ("heart_rate_bpm", 160, 3),
    ("heart_rate_bpm", 44, 2),        # guía: menos de 45 → naranja
    ("body_temp_c", 36.7, 0),
    ("body_temp_c", 38.2, 2),
    ("systolic_mmhg", 118, 0),
    ("systolic_mmhg", 140, 2),        # inclusive: 140 ya cuenta
    ("systolic_mmhg", 180, 2),        # AHA: grave es "más de 180"
    ("systolic_mmhg", 181, 3),
    ("diastolic_mmhg", 120, 2),
    ("diastolic_mmhg", 121, 3),
    ("glucose_mg_dl", 92, 0),
    ("glucose_mg_dl", 65, 2),
    ("glucose_mg_dl", 50, 3),
    ("mood", 4, 0),
    ("mood", 2, 1),
    ("mood", 1, 2),
    ("still_for_s", 600, 1),
    ("humidity_pct", 68, 0),
    ("humidity_pct", 72, 1),
    ("humidity_pct", 80, 2),          # NASA-STD-3001: fuera de 25–75 %
    ("cabin_temp_c", 27.5, 2),        # NASA-STD-3001: fuera de 18–27 °C
    ("heat_index_c", 23.0, 0),
    ("heat_index_c", 33.0, 2),        # NOAA: precaución extrema
    ("condensation_margin_c", 12.6, 0),
    ("condensation_margin_c", 1.5, 2),
])
def test_nivel(indicator, value, level):
    assert level_for(indicator, value).level == level


def test_motivo_y_codigo():
    r = level_for("heart_rate_bpm", 118)
    assert r.system == "cardiovascular"
    assert r.code == "HR_HIGH"
    assert r.reason == "Pulso 118 lat/min, por encima de 100 lat/min"


def test_motivo_por_abajo_con_coma_decimal():
    r = level_for("body_temp_c", 35.2)
    assert r.code == "BODY_TEMP_LOW"
    assert r.reason == "Temperatura corporal 35,2 °C, por debajo de 35,5 °C"


def test_en_rango_no_tiene_motivo():
    r = level_for("heart_rate_bpm", 72)
    assert (r.level, r.code, r.reason) == (0, None, None)


def test_sin_dato_no_es_verde():
    r = level_for("heart_rate_bpm", None)
    assert r.level is None
    assert r.reason == "Pulso: sin dato"
