"""AstroMed: firmware -> SQLite -> local rules engine -> browser."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from astromed_config import PRODUCT_NAME, TEAM_NAME, database_url as configured_database_url, demo_mode, setting
from contracts.schemas import CrewProfile, EventPayload, LatestCrewResponse, ManualCheckPayload, RiskAssessment, TelemetryPayload
from .crew import CREW, profile
from .database import Base, get_db, make_engine
from .models import AssessmentModel, CheckModel, EventModel, RejectedMessage, TelemetryModel
from .services import assess_saved, assessment, persist_message
from .ws_manager import ConnectionManager

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API_KEY = "spacehealth-dev-key-2026"


def now_utc():
    return datetime.now(timezone.utc)


def verify_api_key(request: Request, x_api_key: str | None = Header(default=None)):
    if x_api_key != request.app.state.api_key:
        raise HTTPException(401, "Invalid or missing X-API-Key")


def filtered(db, model, crew_id, start, end, limit, event_type=None):
    if start and end and start > end:
        raise HTTPException(422, "from must be earlier than or equal to to")
    query = select(model)
    if crew_id is not None:
        query = query.where(model.crew_id == crew_id)
    if start:
        query = query.where(model.ts >= start)
    if end:
        query = query.where(model.ts <= end)
    if event_type:
        query = query.where(model.type == event_type)
    rows = list(db.scalars(query.order_by(model.ts.desc(), model.id.desc()).limit(limit)))
    return [row.payload_data for row in reversed(rows)]


def create_app(database_url=None, api_key=None):
    engine = make_engine(database_url or configured_database_url())

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=f"{PRODUCT_NAME} API", description=f"Astronaut health monitoring by {TEAM_NAME}.",
                  version="2026.2", lifespan=lifespan)
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.state.api_key = api_key if api_key is not None else setting("API_KEY", DEFAULT_API_KEY)
    app.state.manager = ConnectionManager()
    origins = [x.strip() for x in setting("CORS_ORIGINS", "*").split(",") if x.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Date"])

    @app.middleware("http")
    async def date_header(request, call_next):
        response = await call_next(request)
        response.headers["Date"] = format_datetime(now_utc(), usegmt=True)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        try:
            with app.state.session_factory() as db:
                db.add(RejectedMessage(received_at=now_utc(), path=request.url.path, errors=errors))
                db.commit()
        except Exception:
            log.exception("Could not store validation failure")
        code = 400 if any(e["type"] == "json_invalid" for e in errors) else 422
        return JSONResponse({"detail": errors}, status_code=code)

    @app.exception_handler(OperationalError)
    async def database_busy(request, exc):
        log.error("Database operation failed: %s", exc)
        return JSONResponse({"detail": "Database temporarily unavailable; retry"}, status_code=503)

    async def ingest(kind, payload, db):
        duplicate, key = persist_message(db, kind, payload)
        result, pending = assess_saved(db, payload.crew_id, key, now_utc())
        if not duplicate and kind != "checks":
            await app.state.manager.broadcast({"type": "telemetry" if kind == "telemetry" else "event",
                                               "data": payload.model_dump(mode="json")})
        if result:
            await app.state.manager.broadcast({"type": "assessment", "data": result})
        return {"ok": True, "duplicate": duplicate, "assessment_pending": pending}

    @app.post("/api/v1/telemetry", dependencies=[Depends(verify_api_key)])
    async def receive_telemetry(payload: TelemetryPayload, db: Session = Depends(get_db)):
        return await ingest("telemetry", payload, db)

    @app.post("/api/v1/events", dependencies=[Depends(verify_api_key)])
    async def receive_event(payload: EventPayload, db: Session = Depends(get_db)):
        return await ingest("events", payload, db)

    @app.post("/api/v1/checks")
    async def receive_check(payload: ManualCheckPayload, db: Session = Depends(get_db)):
        # Deliberately public for the dashboard, as requested by the team.
        return await ingest("checks", payload, db)

    @app.post("/api/v1/assessment", dependencies=[Depends(verify_api_key)], deprecated=True)
    async def receive_assessment(payload: RiskAssessment, db: Session = Depends(get_db)):
        """Legacy import route. Normal operation evaluates locally on every input."""
        if not payload.crew_id:
            raise HTTPException(422, "crew_id is required for an imported assessment")
        data = payload.model_dump(mode="json")
        db.add(AssessmentModel(crew_id=payload.crew_id, ts=payload.ts,
                               overall_level=payload.overall_level, payload_data=data))
        db.commit()
        await app.state.manager.broadcast({"type": "assessment", "data": data})
        return {"ok": True}

    @app.get("/api/v1/crew", response_model=list[CrewProfile])
    def crew_list(db: Session = Depends(get_db)):
        ids = set(CREW)
        for model in (TelemetryModel, EventModel, CheckModel):
            ids.update(x for x in db.scalars(select(model.crew_id).distinct()) if x)
        return [profile(crew_id) for crew_id in sorted(ids)]

    @app.get("/api/v1/crew/active")
    def active_crew(db: Session = Depends(get_db)):
        tel = db.scalar(select(TelemetryModel).order_by(TelemetryModel.ts.desc(), TelemetryModel.id.desc()).limit(1))
        event = db.scalar(select(EventModel).where(EventModel.type == "crew_checkin")
                          .order_by(EventModel.ts.desc(), EventModel.id.desc()).limit(1))
        # The last RFID check-in wins. With several devices sending at once, the
        # newest telemetry alternates between crew members every 2 s.
        if event:
            active = event.crew_id if event.payload_data.get("data", {}).get("action") == "in" else None
            ts = event.ts
        else:
            active, ts = (tel.crew_id, tel.ts) if tel else (None, None)
        return {"crew_id": active, "ts": ts}

    @app.get("/api/v1/crew/{crew_id}/latest", response_model=LatestCrewResponse)
    def latest(crew_id: str, db: Session = Depends(get_db)):
        info = profile(crew_id)
        tel = db.scalar(select(TelemetryModel).where(TelemetryModel.crew_id == crew_id)
                        .order_by(TelemetryModel.ts.desc(), TelemetryModel.id.desc()).limit(1))
        exercise = db.scalar(select(EventModel).where(EventModel.crew_id == crew_id, EventModel.type == "exercise_summary")
                             .order_by(EventModel.ts.desc(), EventModel.id.desc()).limit(1))
        # Re-evaluate at read time: old stored green assessments must not stay fresh forever.
        try:
            result, error = assessment(db, crew_id, now_utc()), None
        except Exception:
            log.exception("Could not evaluate latest state for %s", crew_id)
            result, error = None, "Assessment temporarily unavailable"
        return {"crew_id": crew_id, "crew_name": info["name"], "crew_role": info["role"],
                "assigned": info["assigned"], "telemetry": tel.payload_data if tel else None,
                "assessment": result, "last_exercise": exercise.payload_data if exercise else None,
                "assessment_error": error}

    @app.get("/api/v1/crew/{crew_id}/telemetry")
    def telemetry_history(crew_id: str, start: AwareDatetime | None = Query(None, alias="from"),
                          end: AwareDatetime | None = Query(None, alias="to"),
                          limit: int = Query(3000, ge=1, le=10000), db: Session = Depends(get_db)):
        return filtered(db, TelemetryModel, crew_id, start, end, limit)

    @app.get("/api/v1/crew/{crew_id}/checks")
    def check_history(crew_id: str, start: AwareDatetime | None = Query(None, alias="from"),
                      end: AwareDatetime | None = Query(None, alias="to"),
                      limit: int = Query(1000, ge=1, le=10000), db: Session = Depends(get_db)):
        return filtered(db, CheckModel, crew_id, start, end, limit)

    @app.get("/api/v1/events")
    def events(crew_id: str | None = None, type: str | None = None,
               start: AwareDatetime | None = Query(None, alias="from"), end: AwareDatetime | None = Query(None, alias="to"),
               limit: int = Query(1000, ge=1, le=10000), db: Session = Depends(get_db)):
        return filtered(db, EventModel, crew_id, start, end, limit, type)

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        await app.state.manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            app.state.manager.disconnect(websocket)

    @app.get("/api/v1/status")
    def status():
        return {"ok": True, "system": PRODUCT_NAME, "team": TEAM_NAME, "server_time": now_utc(),
                "demo_mode": demo_mode()}

    frontend = ROOT / "frontend" / "boceto"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/")
        def root():
            return status()
    return app


app = create_app()
