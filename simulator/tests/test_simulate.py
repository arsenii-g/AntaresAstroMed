import json
import random
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from risk import evaluate
from simulator.simulate import (
    Sender, dew_point_c, heat_index_c, make_events, make_telemetry,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
TS = datetime(2026, 11, 14, 10, 30, 5, tzinfo=timezone.utc)


def keys(d):
    return {k: keys(v) if isinstance(v, dict) else None for k, v in d.items()}


def test_telemetria_con_la_forma_del_contrato():
    example = json.loads((CONTRACTS / "telemetry.example.json").read_text(encoding="utf-8"))
    for scenario in ("healthy", "worsening", "no-data"):
        msg = make_telemetry(scenario, 3, TS, random.Random(1))
        assert keys(msg) == keys(example)
        assert msg["vitals"]["resp_rate_bpm"] is None


def test_humedad_entera_y_hr_quality_numero():
    msg = make_telemetry("healthy", 0, TS, random.Random(1))
    assert isinstance(msg["cabin"]["humidity_pct"], int)
    assert isinstance(msg["vitals"]["hr_quality"], float)


def test_sin_datos_llega_todo_null():
    msg = make_telemetry("no-data", 0, TS, random.Random(1))
    assert msg["crew_id"] is None
    assert msg["vitals"]["hr_quality"] == 0
    assert all(v is None for v in msg["cabin"].values())


def test_solo_los_tres_tipos_de_evento():
    rng = random.Random(1)
    types = {e["type"] for t in range(100) for e in make_events("worsening", t, TS, rng)}
    assert types <= {"crew_checkin", "inactivity", "exercise_summary"}


def test_formulas_de_cabina():
    assert abs(dew_point_c(23.0, 45) - 10.4) <= 0.2       # valor del contrato
    assert heat_index_c(23.0, 45) == 23.0                  # por debajo de 80 °F
    assert abs(heat_index_c(32.2, 60) - 37.8) <= 0.5       # tabla de NOAA: 90 °F y 60 % = 100 °F (37,8 °C)


def test_sano_sale_verde_y_empeora_llega_a_rojo():
    def last_level(scenario):
        from datetime import timedelta
        rng, tel = random.Random(1), []
        for t in range(70):
            tel.append(make_telemetry(scenario, t, TS + timedelta(seconds=5 * t), rng))
        return evaluate(tel[-12:], [], [], TS + timedelta(seconds=5 * 69))["overall_level"]
    assert last_level("healthy") == 0
    assert last_level("worsening") == 3


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


# --- escenario demo e historia ----------------------------------------------------

from risk.indicators import load_thresholds
from simulator.simulate import (
    DEMO_CREW_B, DEMO_PUSHUP_TICK, DEMO_SWITCH_TICK, demo_crew, make_history,
)


def run_demo(monkeypatch):
    """Evalúa cada envío del guion como lo haría la API, por crew_id."""
    monkeypatch.setenv("SPACEHEALTH_DEMO", "1")
    from datetime import timedelta
    rng, tel, ev, out = random.Random(1), [], [], {}
    for t in range(24):
        ts = TS + timedelta(seconds=5 * t)
        tel.append(make_telemetry("demo", t, ts, rng))
        ev.extend(make_events("demo", t, ts, rng))
        crew = demo_crew(t)
        if crew:
            mine = lambda msgs: [m for m in msgs if m.get("crew_id") == crew]
            out[t] = evaluate(mine(tel[-20:]), mine(ev), [], ts)
    return out, ev


def test_guion_de_la_demo(monkeypatch):
    out, events = run_demo(monkeypatch)
    still_amber = [t for t, r in out.items() if "Do a set of push-ups or move for a few minutes" in r["recommendations"]]
    assert still_amber and max(still_amber) < DEMO_PUSHUP_TICK          # ámbar antes de las flexiones
    assert out[DEMO_PUSHUP_TICK]["overall_level"] == 0                     # y verde justo después
    assert out[DEMO_SWITCH_TICK]["crew_id"] == DEMO_CREW_B
    assert out[DEMO_SWITCH_TICK]["overall_level"] == 1                     # pulso aún no sostenido
    assert out[DEMO_SWITCH_TICK + 2]["overall_level"] == 3                 # 3 lecturas: rojo
    assert out[DEMO_SWITCH_TICK + 2]["earth_summary"].startswith("SPACEHEALTH MEDICAL SUMMARY")
    kinds = [(e["type"], e["data"].get("action")) for e in events]
    assert ("inactivity", None) in kinds
    assert kinds.count(("crew_checkin", "in")) == 2 and ("crew_checkin", "out") in kinds


def test_historia_de_una_semana_da_tendencias():
    checks, events = make_history("worsening", 7, TS, random.Random(1))
    assert len(checks) == 7 and len(events) == 7
    assert all(m["ts"] < "2026-11-14T10:30:05Z" for m in checks + events)    # todo es anterior a TS
    result = evaluate([], events, checks, TS)
    crossing = {t["indicator"] for t in result["trends"] if t["crosses_threshold_in_days"] is not None}
    assert {"systolic_mmhg", "pushup_reps"} <= crossing


def test_historia_sana_no_cruza_nada():
    checks, events = make_history("healthy", 7, TS, random.Random(1))
    result = evaluate([], events, checks, TS)
    assert result["trends"] and all(t["crosses_threshold_in_days"] is None for t in result["trends"])


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


def test_quieto_siempre_con_3_s_o_mas():
    rng = random.Random(1)
    for scenario in ("healthy", "worsening", "no-data", "demo"):
        for t in range(40):
            m = make_telemetry(scenario, t, TS, rng)["motion"]
            if m["activity"] == "moving":
                assert m["still_for_s"] == 0
            else:
                assert m["still_for_s"] >= 3


def test_segundo_tripulante_es_la_tarjeta_del_kit():
    assert DEMO_CREW_B == "336F8312"
