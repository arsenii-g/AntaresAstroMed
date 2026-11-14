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
    for scenario in ("sano", "empeora", "sin-datos"):
        msg = make_telemetry(scenario, 3, TS, random.Random(1))
        assert keys(msg) == keys(example)
        assert msg["vitals"]["resp_rate_bpm"] is None


def test_humedad_entera_y_hr_quality_numero():
    msg = make_telemetry("sano", 0, TS, random.Random(1))
    assert isinstance(msg["cabin"]["humidity_pct"], int)
    assert isinstance(msg["vitals"]["hr_quality"], float)


def test_sin_datos_llega_todo_null():
    msg = make_telemetry("sin-datos", 0, TS, random.Random(1))
    assert msg["crew_id"] is None
    assert msg["vitals"]["hr_quality"] == 0
    assert all(v is None for v in msg["cabin"].values())


def test_solo_los_tres_tipos_de_evento():
    rng = random.Random(1)
    types = {e["type"] for t in range(100) for e in make_events("empeora", t, TS, rng)}
    assert types <= {"crew_checkin", "inactivity", "exercise_summary"}


def test_formulas_de_cabina():
    assert abs(dew_point_c(23.0, 45) - 10.4) <= 0.2       # valor del contrato
    assert heat_index_c(23.0, 45) == 23.0                  # por debajo de 80 °F
    assert abs(heat_index_c(32.2, 60) - 37.8) <= 0.5       # tabla de NOAA: 90 °F y 60 % = 100 °F (37,8 °C)


def test_sano_sale_verde_y_empeora_llega_a_rojo():
    def last_level(scenario):
        rng, tel = random.Random(1), []
        for t in range(70):
            tel.append(make_telemetry(scenario, t, TS, rng))
        return evaluate(tel[-12:], [], [], TS)["overall_level"]
    # Las horas no avanzan en este test: todos los mensajes valen como recientes.
    assert last_level("sano") == 0
    assert last_level("empeora") == 3


# --- reintentos como el ESP32 -------------------------------------------------------

def serve(statuses):
    """Servidor que responde con los códigos de la lista, uno por petición."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("X-API-Key"), body))
            self.send_response(statuses.pop(0) if statuses else 200)
            self.end_headers()

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
