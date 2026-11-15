#!/usr/bin/env python3
"""Test backend for the ESP32: prints what arrives and replies {"ok": true}.

    python3 mock_backend.py            # listens on 0.0.0.0:8000

In firmware/esp32_gateway/config.h set API_BASE = "http://<this PC's IP>:8000"
and API_KEY = "change-this-key" (or change the one below).
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = "change-this-key"


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # the ESP32 uses this to get the time when there is no NTP
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
    print("Test backend on http://0.0.0.0:8000")
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
