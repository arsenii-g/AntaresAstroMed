import json
import random
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from contracts.schemas import EventPayload, TelemetryPayload
from risk import evaluate
from simulator.simulate import (
    ANCHORS, CONFIG_PATH, Device, Sender, Severity, build_devices, condensation_risk,
    dew_point_c, drop_level, heat_index_c, interpolate, load_config, next_reps,
)

START = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)


def config(levels, mode="fixed", **extra):
    return {"mode": mode, "interval_s": 2, "pushup_every_s": 20, "normal": {"seed": 1},
            "crew": [{"crew_id": c, "device_id": f"esp32-sim-{i + 1}", "level": lv}
                     for i, (c, lv) in enumerate(levels.items())], **extra}


def run(device: Device, seconds: int):
    """Telemetría y eventos de `seconds` segundos, con su ts."""
    telemetry, events = [], [device.checkin(START)]
    for tick in range(seconds // device.interval_s):
        evs, tel = device.tick(START + timedelta(seconds=2 + tick * device.interval_s))
        telemetry.append(tel)
        events.extend(evs)
    return telemetry, events


def levels_at_end(device: Device, seconds: int = 240):
    telemetry, events = run(device, seconds)
    now = START + timedelta(seconds=2 + seconds - device.interval_s)
    return evaluate(telemetry[-30:], events, [], now)


# --- forma de los mensajes ---------------------------------------------------------

def test_config_por_defecto_tiene_dos_tripulantes_del_kit():
    cfg = load_config(CONFIG_PATH)
    assert [c["crew_id"] for c in cfg["crew"]] == ["F3786E09", "336F8312"]
    assert cfg["mode"] in ("fixed", "normal") and cfg["interval_s"] == 2
    assert len({c["device_id"] for c in cfg["crew"]}) == 2


def test_mensajes_pasan_los_contratos_de_la_api():
    device = build_devices(config({"F3786E09": 3}))[0]
    telemetry, events = run(device, 60)
    for msg in telemetry:
        TelemetryPayload.model_validate(msg)
        assert isinstance(msg["cabin"]["humidity_pct"], int) and msg["vitals"]["resp_rate_bpm"] is None
        assert (msg["motion"]["activity"] == "moving") == (msg["motion"]["still_for_s"] == 0)
        assert msg["motion"]["still_for_s"] == 0 or msg["motion"]["still_for_s"] >= 3
    for ev in events:
        EventPayload.model_validate(ev)
    assert {e["type"] for e in events} == {"crew_checkin", "exercise_summary"}
    assert len({(m["device_id"], m["ts"]) for m in telemetry}) == len(telemetry)   # nunca un ts repetido


def test_formulas_de_cabina():
    assert dew_point_c(23, 45) == 10.4
    assert heat_index_c(22.5, 45) == 22.5
    assert condensation_risk(1.5) == "high" and condensation_risk(5) == "medium" and condensation_risk(6) == "low"


def test_primera_serie_no_cae_en_los_3_s_del_fichaje():
    device = build_devices(config({"F3786E09": 0}))[0]
    _, events = run(device, 20)
    first = next(e for e in events if e["type"] == "exercise_summary")
    assert datetime.fromisoformat(first["ts"].replace("Z", "+00:00")) - START > timedelta(seconds=4)


# --- niveles fijos -------------------------------------------------------------------

@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_nivel_fijo_da_ese_nivel_en_cada_sistema(level):
    result = levels_at_end(build_devices(config({"F3786E09": level}))[0])
    for system in ("cardiovascular", "musculoskeletal", "environment"):
        assert result["systems"][system]["level"] == level, (system, result["systems"][system])
    assert result["systems"]["neuro"]["level"] is None             # solo con chequeo manual
    assert result["overall_level"] == level


def test_nivel_por_sistema():
    result = levels_at_end(build_devices(config({"F3786E09": {"cardiovascular": 3, "environment": 1}}))[0])
    levels = {k: v["level"] for k, v in result["systems"].items()}
    assert levels == {"cardiovascular": 3, "neuro": None, "musculoskeletal": 0, "environment": 1}


def test_nivel_fijo_no_da_avisos_de_tendencia_falsos():
    for level in (0, 1, 2):
        result = levels_at_end(build_devices(config({"F3786E09": level}))[0])
        assert not [t for t in result["trends"] if t["basis"] == "time" and t["crosses_in"] is not None]


def test_nivel_invalido_se_rechaza():
    with pytest.raises(ValueError):
        build_devices(config({"F3786E09": 4}))
    with pytest.raises(ValueError):
        build_devices(config({"F3786E09": 1}, mode="random"))


def test_override_de_nivel_y_modo_desde_la_linea_de_comandos(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(config({"F3786E09": 0, "336F8312": 0})))
    args = type("A", (), {"mode": "normal", "level": ["336F8312=3"], "url": None, "api_key": None})()
    cfg = load_config(path, args)
    assert cfg["mode"] == "normal" and cfg["crew"][1]["level"] == 3 and cfg["crew"][0]["level"] == 0


def test_flexiones_mantienen_la_caida_del_nivel_frente_a_su_media():
    for level, drop in enumerate(ANCHORS["drop"]):
        reps, rng = [], random.Random(level)
        for _ in range(15):
            reps.append(next_reps(reps, drop, rng))
        for i in range(3, len(reps)):                               # tras las 3 series de basal
            baseline = sum(reps[:i]) / i
            assert drop_level(max(0, (baseline - reps[i]) / baseline * 100)) == level, (level, reps)


# --- modo normal ---------------------------------------------------------------------

def test_modo_normal_recorre_niveles_y_las_rectas_lo_ven():
    device = build_devices(config({"F3786E09": 0}, mode="normal"))[0]
    telemetry, events = run(device, 600)
    seen, crossing = set(), set()
    for i in range(30, len(telemetry), 5):
        now = START + timedelta(seconds=2 + i * 2)
        result = evaluate(telemetry[i - 29:i + 1], [e for e in events if e["ts"] <= telemetry[i]["ts"]], [], now)
        seen.add(result["overall_level"])
        crossing |= {t["indicator"] for t in result["trends"] if t["crosses_in"] is not None}
    assert {0, 1, 2, 3} <= seen
    assert {"heart_rate_bpm", "cabin_temp_c"} <= crossing


def test_severidad_va_en_rampa_hacia_su_objetivo():
    sev = Severity(0, "normal", random.Random(3), {"change_every_s": [1, 1], "ramp_s_per_level": 10,
                                                   "level_weights": [0, 0, 0, 1]})
    values = [sev.step(2) for _ in range(20)]
    assert values[-1] == 3 and all(b >= a for a, b in zip(values, values[1:]))
    assert interpolate((0, 10, 20, 30), 1.5) == 15


# --- reintentos como el ESP32 -------------------------------------------------------

def serve(statuses):
    """Servidor que responde con los códigos de la lista, uno por petición."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("X-API-Key"), body))
            reply = statuses.pop(0) if statuses else 200
            status, body = reply if isinstance(reply, tuple) else (reply, b"")
            self.send_response(status)
            if 300 <= status < 400:
                self.send_header("Location", "/otra")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def test_reintenta_5xx_y_manda_la_clave():
    server, seen = serve([503, 500, 201])
    try:
        sender = Sender(f"http://127.0.0.1:{server.server_port}", "demo", sleep=lambda s: None)
        sender.push("/api/v1/telemetry", {"n": 1})
        sender.flush()
    finally:
        server.shutdown()
    assert len(seen) == 3
    assert seen[0][:2] == ("/api/v1/telemetry", "demo")
    assert sender.stats == {"sent": 1, "duplicate": 0, "dropped": 0, "retries": 2}


def test_409_es_duplicado_y_422_se_descarta():
    server, seen = serve([409, 422, 200])
    try:
        sender = Sender(f"http://127.0.0.1:{server.server_port}", None, sleep=lambda s: None)
        for n in range(3):
            sender.push("/api/v1/events", {"n": n})
        sender.flush()
    finally:
        server.shutdown()
    assert len(seen) == 3
    assert sender.stats == {"sent": 1, "duplicate": 1, "dropped": 1, "retries": 0}
    assert not sender.queue


def test_sin_api_guarda_la_cola():
    waits = []
    sender = Sender("http://127.0.0.1:9", None, timeout=0.2, sleep=waits.append)
    sender.push("/api/v1/telemetry", {"n": 1})
    sender.flush()
    assert waits == [1, 2, 4, 8]          # 1+2+4+8 = 15; el siguiente (16) pasaría de 30 s
    assert len(sender.queue) == 1


def test_408_429_3xx_y_ok_false_se_reintentan_como_en_el_esp32():
    server, seen = serve([429, 408, 301, (200, b'{"ok": false}'), (200, b'{"ok": true}')])
    try:
        sender = Sender(f"http://127.0.0.1:{server.server_port}", None, sleep=lambda s: None)
        sender.push("/api/v1/telemetry", {"n": 1})
        sender.flush()
    finally:
        server.shutdown()
    assert len(seen) == 5
    assert all(path == "/api/v1/telemetry" for path, _, _ in seen)   # no siguió el 301
    assert sender.stats == {"sent": 1, "duplicate": 0, "dropped": 0, "retries": 4}


