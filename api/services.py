import hashlib
import json
import logging
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from contracts.schemas import RiskAssessment
from risk import evaluate
from .models import AssessmentModel, CheckModel, EventModel, IngestionReceipt, TelemetryModel

log = logging.getLogger(__name__)


def recent(db, model, crew_id, now, window):
    query = select(model).where(model.crew_id == crew_id, model.ts >= now - window,
                                model.ts <= now + timedelta(seconds=5)).order_by(model.ts, model.id)
    return [row.payload_data for row in db.scalars(query)]


def assessment(db, crew_id, now):
    result = evaluate(recent(db, TelemetryModel, crew_id, now, timedelta(minutes=1)),
                      recent(db, EventModel, crew_id, now, timedelta(days=7)),
                      recent(db, CheckModel, crew_id, now, timedelta(days=7)), now)
    result["crew_id"] = crew_id
    return RiskAssessment.model_validate(result).model_dump(mode="json")


def persist_message(db, kind, payload):
    model = {"telemetry": TelemetryModel, "events": EventModel, "checks": CheckModel}[kind]
    owner = payload.crew_id if kind == "checks" else payload.device_id
    event_type = payload.type if kind == "events" else kind
    identity = [kind, owner, payload.ts.isoformat(), event_type]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    inserted = db.execute(insert(IngestionReceipt).values(key=key, assessed=False)
                          .on_conflict_do_nothing(index_elements=["key"])).rowcount
    if not inserted:
        db.rollback()
        return True, key
    query = select(model.id).where(model.ts == payload.ts)
    query = query.where(model.crew_id == owner) if kind == "checks" else query.where(model.device_id == owner)
    if kind == "events":
        query = query.where(model.type == payload.type)
    existing = db.scalar(query.limit(1)) is not None
    if not existing:
        values = {"crew_id": payload.crew_id, "ts": payload.ts,
                  "payload_data": payload.model_dump(mode="json")}
        if kind != "checks":
            values["device_id"] = payload.device_id
        if kind == "telemetry":
            values["met_s"] = payload.met_s
        if kind == "events":
            values.update(type=payload.type, severity=payload.severity)
        db.add(model(**values))
    db.commit()
    return existing, key


def assess_saved(db, crew_id, receipt_key, now):
    receipt = db.get(IngestionReceipt, receipt_key)
    if receipt.assessed:
        return None, False
    try:
        result = assessment(db, crew_id, now) if crew_id else None
        if result:
            db.add(AssessmentModel(crew_id=crew_id, ts=now, overall_level=result["overall_level"], payload_data=result))
        receipt.assessed = True
        db.commit()
        return result, False
    except Exception:
        db.rollback()
        log.exception("Risk evaluation failed for %s; input remains stored", crew_id)
        return None, True
