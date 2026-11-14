"""Backend de PRUEBA para el frontend. No es la API del proyecto (esa es api/, de Jesus).

Hace lo mínimo de los contratos para ver la web con datos reales del motor:

- POST /api/v1/telemetry, /api/v1/events, /api/v1/checks  (① y ②)
- llama a risk.evaluate() con telemetría de 1 min y eventos y chequeos de 7 días (③)
- GET /api/v1/crew/{crew_id}/latest y WebSocket /ws con {"type", "data"}  (④)

Todo en memoria: al pararlo se pierde. Duplicados por (device_id o crew_id, ts, tipo) → 409.

    python -m uvicorn server:app --app-dir frontend/dev-backend --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from risk import evaluate  # noqa: E402  (motor de Arsenii, dentro del mismo proceso)

log = logging.getLogger("dev-backend")
logging.basicConfig(level=logging.INFO, format="[dev-backend] %(message)s")

API_KEY = os.environ.get("SPACEHEALTH_API_KEY")  # si no se define, no se comprueba
TELEMETRY_WINDOW = timedelta(minutes=1)
HISTORY_WINDOW = timedelta(days=7)

app = FastAPI(title="SpaceHealth dev backend (not the real API)")
store: dict[str, list[dict]] = {"telemetry": [], "events": [], "checks": []}
seen: set[tuple] = set()
latest: dict[str, dict] = {}  # crew_id -> {"telemetry": ..., "assessment": ...}
clients: set[WebSocket] = set()


def _ts(msg: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(msg.get("ts")).replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent(kind: str, crew_id: str, now: datetime, window: timedelta) -> list[dict]:
    out = []
    for m in store[kind]:
        ts = _ts(m)
        if m.get("crew_id") == crew_id and ts is not None and ts >= now - window:
            out.append(m)
    return out


async def _broadcast(kind: str, data: dict) -> None:
    for ws in list(clients):
        try:
            await ws.send_json({"type": kind, "data": data})
        except Exception:
            clients.discard(ws)


async def _assess(crew_id: str) -> None:
    now = datetime.now(timezone.utc)
    try:
        assessment = evaluate(
            telemetry=_recent("telemetry", crew_id, now, TELEMETRY_WINDOW),
            events=_recent("events", crew_id, now, HISTORY_WINDOW),
            manual_checks=_recent("checks", crew_id, now, HISTORY_WINDOW),
            now=now,
        )
    except Exception:  # un fallo del motor nunca tumba el endpoint
        log.exception("evaluate() failed")
        return
    assessment["crew_id"] = assessment.get("crew_id") or crew_id
    latest.setdefault(crew_id, {})["assessment"] = assessment
    levels = {k: v.get("level") for k, v in assessment["systems"].items()}
    log.info("%s overall=%s %s trends=%d", crew_id, assessment["overall_level"], levels, len(assessment["trends"]))
    await _broadcast("assessment", assessment)


async def _ingest(request: Request, kind: str, ws_type: str | None, api_key: str | None):
    if API_KEY and api_key != API_KEY:
        return JSONResponse({"ok": False, "detail": "bad X-API-Key"}, status_code=401)
    try:
        msg = json.loads(await request.body())
        assert isinstance(msg, dict)
    except (ValueError, AssertionError):
        return JSONResponse({"ok": False, "detail": "invalid JSON"}, status_code=400)

    key = (msg.get("device_id") or msg.get("crew_id"), msg.get("ts"), msg.get("type") if kind == "events" else kind)
    if key in seen:
        return JSONResponse({"ok": True, "duplicate": True}, status_code=409)
    seen.add(key)
    store[kind].append(msg)
    _prune()

    crew_id = msg.get("crew_id")
    if kind == "telemetry" and crew_id:
        latest.setdefault(crew_id, {})["telemetry"] = msg
    if ws_type:
        await _broadcast(ws_type, msg)
    if crew_id:
        await _assess(crew_id)
    return {"ok": True}


def _prune() -> None:
    now = datetime.now(timezone.utc)
    for kind, window in (("telemetry", TELEMETRY_WINDOW * 5), ("events", HISTORY_WINDOW), ("checks", HISTORY_WINDOW)):
        store[kind] = [m for m in store[kind] if (_ts(m) or now) >= now - window]


@app.get("/")
async def root():
    # El ESP32 toma la hora de la cabecera Date si no tiene NTP.
    return {"ok": True, "service": "SpaceHealth dev backend"}


@app.post("/api/v1/telemetry")
async def post_telemetry(request: Request, x_api_key: str | None = Header(default=None)):
    return await _ingest(request, "telemetry", "telemetry", x_api_key)


@app.post("/api/v1/events")
async def post_event(request: Request, x_api_key: str | None = Header(default=None)):
    return await _ingest(request, "events", "event", x_api_key)


@app.post("/api/v1/checks")
async def post_check(request: Request, x_api_key: str | None = Header(default=None)):
    # Un chequeo no se reenvía en bruto: emite directamente la evaluación nueva.
    return await _ingest(request, "checks", None, x_api_key)


@app.get("/api/v1/crew/{crew_id}/latest")
async def get_latest(crew_id: str):
    if crew_id not in latest:
        return JSONResponse({"detail": "no data for this crew_id"}, status_code=404)
    return {"telemetry": latest[crew_id].get("telemetry"), "assessment": latest[crew_id].get("assessment")}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
