import pytest

from risk.indicators import level_for, load_thresholds

SYSTEMS = {"cardiovascular", "neuro", "musculoskeletal", "environment"}


# --- the thresholds file is well formed -------------------------------

@pytest.mark.parametrize("name,spec", load_thresholds().items())
def test_thresholds_well_formed(name, spec):
    assert spec["system"] in SYSTEMS
    for key in ("label", "unit", "code", "source"):
        assert spec[key], f"{name}: falta {key}"
    assert "nasa_ref" in spec, f"{name}: missing nasa_ref (null if NASA gives no limit)"
    for side in ("high", "low"):
        cuts = spec.get(side, [])
        assert len(cuts) == 3, f"{name}.{side} debe tener 3 cortes"
        used = [c for c in cuts if c is not None]
        if side == "high":
            assert used == sorted(used), f"{name}.high debe ir de menor a mayor"
        else:
            assert used == sorted(used, reverse=True), f"{name}.low debe ir de mayor a menor"
    assert any(c is not None for c in spec["high"] + spec["low"]), f"{name} no tiene cortes"


# --- levels ----------------------------------------------------------------

@pytest.mark.parametrize("indicator,value,level", [
    ("heart_rate_bpm", 72, 0),
    ("heart_rate_bpm", 100, 0),       # the cut is not included: the value must exceed 100
    ("heart_rate_bpm", 118, 1),
    ("heart_rate_bpm", 125, 2),       # guide: above 120 -> orange
    ("heart_rate_bpm", 160, 3),
    ("heart_rate_bpm", 44, 2),        # guide: below 45 -> orange
    ("body_temp_c", 36.7, 0),
    ("body_temp_c", 38.2, 2),
    ("systolic_mmhg", 118, 0),
    ("systolic_mmhg", 140, 2),        # inclusive: 140 already counts
    ("systolic_mmhg", 180, 2),        # AHA: severe is "above 180"
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
    ("pushup_drop_pct", 5, 0),
    ("pushup_drop_pct", 15, 1),
    ("pushup_drop_pct", 20, 1),       # NASA [V1 4024]: 80 % of baseline still complies
    ("pushup_drop_pct", 25, 2),       # below 80 %: does not comply
    ("pushup_drop_pct", 45, 3),
    ("humidity_pct", 58, 0),
    ("humidity_pct", 62, 1),          # NASA-STD-3001 [V2 6013]: outside 30-60 %
    ("humidity_pct", 80, 2),          # NASA-STD-3001: outside 25-75 %
    ("cabin_temp_c", 25.5, 1),        # NASA-STD-3001 [V2 6013]: outside 20-25 °C
    ("cabin_temp_c", 27.5, 2),        # NASA-STD-3001 [V2 6012]: outside 18-27 °C
    ("heat_index_c", 23.0, 0),
    ("heat_index_c", 33.0, 2),        # NOAA: extreme caution
    ("condensation_margin_c", 12.6, 0),
    ("condensation_margin_c", 1.5, 2),
])
def test_level(indicator, value, level):
    assert level_for(indicator, value).level == level


def test_reason_and_code():
    r = level_for("heart_rate_bpm", 118)
    assert r.system == "cardiovascular"
    assert r.code == "HR_HIGH"
    assert r.reason == "Heart rate 118 bpm, above 100 bpm"


def test_reason_below_with_decimal_point():
    r = level_for("body_temp_c", 35.2)
    assert r.code == "BODY_TEMP_LOW"
    assert r.reason == "Body temperature 35.2 °C, below 35.5 °C"


def test_in_range_has_no_reason():
    r = level_for("heart_rate_bpm", 72)
    assert (r.level, r.code, r.reason) == (0, None, None)


def test_no_data_is_not_green():
    r = level_for("heart_rate_bpm", None)
    assert r.level is None
    assert r.reason == "Heart rate: no data"


def test_indicators_with_nasa_limit():
    con_nasa = {k for k, v in load_thresholds().items() if v["nasa_ref"]}
    assert con_nasa == {"cabin_temp_c", "humidity_pct", "pushup_drop_pct"}


def test_restate_uses_nearest_cut_if_its_own_is_null():
    from risk.indicators import level_for, restate
    low = level_for("glucose_mg_dl", 50)                 # low cuts [null, 70, 54]
    assert low.level == 3
    assert restate(low, 1, "test").cut == 70             # level 1 has no low cut: it does not invent 54
    assert restate(low, 2, "test").cut == 70


def test_text_and_bool_count_as_no_data():
    from risk.indicators import level_for
    assert level_for("heart_rate_bpm", "80").level is None
    assert level_for("heart_rate_bpm", True).level is None
