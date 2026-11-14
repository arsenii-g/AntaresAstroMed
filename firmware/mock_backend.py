#!/usr/bin/env python3
"""Backend de prueba para el ESP32: imprime lo que llega y responde {"ok": true}.

    python3 mock_backend.py            # escucha en 0.0.0.0:8000

En firmware/esp32_gateway/config.h pon API_BASE = "http://<IP de este PC>:8000"
y API_KEY = "cambia-esta-clave" (o cambia la de abajo).
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = "cambia-esta-clave"


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # el ESP32 lo usa para sacar la hora si no hay NTP
        self._reply(200, {"ok": True})

    def do_POST(self):
        if self.headers.get("X-API-Key") != API_KEY:
            return self._reply(401, {"ok": False, "error": "bad api key"})
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            msg = json.loads(raw)
        except ValueError:
            return self._reply(400, {"ok": False, "error": "bad json"})
        print(f"\n{self.path}\n{json.dumps(msg, indent=2, ensure_ascii=False)}", flush=True)
        self._reply(200, {"ok": True})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Backend de prueba en http://0.0.0.0:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
