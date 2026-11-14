from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import engine, Base, get_db
from .models import TelemetryModel, EventModel, CheckModel, AssessmentModel
from .ws_manager import manager
from contracts.schemas import (
    TelemetryPayload,
    EventPayload,
    ManualCheckPayload,
    RiskAssessment,
    LatestCrewResponse
)

# Inicializar tablas en SQLite
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SpaceHealth API",
    version="2026.1",
    description="Backend oficial para NASA Space Apps 2026"
)

# Configurar CORS para el Frontend de Vue (puerto 5173 por defecto)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY_SECRET = "spacehealth-dev-key-2026"


def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida o no proporcionada"
        )
    return x_api_key


# --- RUTA RAIZ: Sincronización horaria para el ESP32 ---
@app.get("/")
def read_root():
    """Devuelve la fecha actual en formato HTTP para que el ESP32 ajuste su reloj NTP local."""
    now = datetime.now(timezone.utc)
    return {
        "status": "online",
        "system": "SpaceHealth API",
        "server_time": now.isoformat()
    }


# --- 1. TELEMETRÍA (ESP32 -> API) ---
@app.post("/api/v1/telemetry", status_code=status.HTTP_201_CREATED)
async def receive_telemetry(payload: TelemetryPayload, db: Session = Depends(get_db),
                            api_key: str = Depends(verify_api_key)):
    # Guardar en SQLite
    db_item = TelemetryModel(
        device_id=payload.device_id,
        ts=payload.ts,
        met_s=payload.met_s,
        crew_id=payload.crew_id,
        payload_data=payload.model_dump(mode="json")
    )
    db.add(db_item)
    db.commit()

    # Broadcast en tiempo real por WebSocket
    await manager.broadcast({
        "type": "telemetry",
        "data": payload.model_dump(mode="json")
    })

    return {"status": "success", "message": "Telemetría registrada correctamente"}


# --- 1b. EVENTOS (ESP32 -> API) ---
@app.post("/api/v1/events", status_code=status.HTTP_201_CREATED)
async def receive_event(payload: EventPayload, db: Session = Depends(get_db), api_key: str = Depends(verify_api_key)):
    db_item = EventModel(
        device_id=payload.device_id,
        ts=payload.ts,
        crew_id=payload.crew_id,
        type=payload.type,
        severity=payload.severity,
        payload_data=payload.model_dump(mode="json")
    )
    db.add(db_item)
    db.commit()

    # Broadcast por WebSocket
    await manager.broadcast({
        "type": "event",
        "data": payload.model_dump(mode="json")
    })

    return {"status": "success", "message": "Evento registrado"}


# --- 2. CHEQUEO MANUAL (Frontend -> API) ---
@app.post("/api/v1/checks", status_code=status.HTTP_201_CREATED)
async def receive_manual_check(payload: ManualCheckPayload, db: Session = Depends(get_db)):
    db_item = CheckModel(
        crew_id=payload.crew_id,
        ts=payload.ts,
        payload_data=payload.model_dump(mode="json")
    )
    db.add(db_item)
    db.commit()

    # Notificar por WebSocket
    await manager.broadcast({
        "type": "check",
        "data": payload.model_dump(mode="json")
    })

    return {"status": "success", "message": "Chequeo manual registrado"}


# --- 3. EVALUACIÓN DE RIESGO (Motor Python -> API) ---
@app.post("/api/v1/assessment", status_code=status.HTTP_201_CREATED)
async def receive_assessment(payload: RiskAssessment, db: Session = Depends(get_db),
                             api_key: str = Depends(verify_api_key)):
    db_item = AssessmentModel(
        crew_id=payload.crew_id,
        ts=payload.ts,
        overall_level=payload.overall_level,
        payload_data=payload.model_dump(mode="json")
    )
    db.add(db_item)
    db.commit()

    # Broadcast por WebSocket
    await manager.broadcast({
        "type": "assessment",
        "data": payload.model_dump(mode="json")
    })

    return {"status": "success", "message": "Evaluación de riesgo procesada"}


# --- GET: ÚLTIMO ESTADO DEL TRIPULANTE (Para la carga inicial de Vue) ---
@app.get("/api/v1/crew/{crew_id}/latest", response_model=LatestCrewResponse)
def get_latest_crew(crew_id: str, db: Session = Depends(get_db)):
    # Buscar última telemetría
    last_tel = db.query(TelemetryModel).filter(TelemetryModel.crew_id == crew_id).order_by(
        TelemetryModel.ts.desc()).first()

    # Buscar última evaluación de riesgo
    last_ass = db.query(AssessmentModel).filter(AssessmentModel.crew_id == crew_id).order_by(
        AssessmentModel.ts.desc()).first()

    # Nombres de tripulantes de ejemplo oficiales
    crew_names = {
        "F3786E09": {"name": "Cmdr. Elena Vance", "role": "Comandante"},
        "04D4E5F6": {"name": "Dr. Marcus Chen", "role": "Oficial Médico"}
    }

    crew_info = crew_names.get(crew_id, {"name": f"Tripulante {crew_id}", "role": "Especialista"})

    return {
        "crew_id": crew_id,
        "crew_name": crew_info["name"],
        "crew_role": crew_info["role"],
        "telemetry": last_tel.payload_data if last_tel else None,
        "assessment": last_ass.payload_data if last_ass else None
    }


# --- GET: HISTÓRICO DE TELEMETRÍA ---
@app.get("/api/v1/crew/{crew_id}/telemetry")
def get_crew_telemetry_history(crew_id: str, db: Session = Depends(get_db)):
    records = db.query(TelemetryModel).filter(TelemetryModel.crew_id == crew_id).order_by(TelemetryModel.ts.asc()).all()
    return [r.payload_data for r in records]


# --- WEBSOCKET ENDPOINT ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Mantener conexión abierta escuchando pings del cliente
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)