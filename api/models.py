from sqlalchemy import Boolean, Column, Integer, JSON, String
from .database import Base, UTCDateTime


class TelemetryModel(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, index=True)
    ts = Column(UTCDateTime, index=True)
    met_s = Column(Integer)
    crew_id = Column(String, index=True, nullable=True)
    payload_data = Column(JSON)


class EventModel(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, index=True)
    ts = Column(UTCDateTime, index=True)
    crew_id = Column(String, index=True, nullable=True)
    type = Column(String, index=True)
    severity = Column(String)
    payload_data = Column(JSON)


class CheckModel(Base):
    __tablename__ = "checks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    crew_id = Column(String, index=True)
    ts = Column(UTCDateTime, index=True)
    payload_data = Column(JSON)


class AssessmentModel(Base):
    __tablename__ = "assessments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    crew_id = Column(String, index=True)
    ts = Column(UTCDateTime, index=True)
    overall_level = Column(Integer, nullable=True)
    payload_data = Column(JSON)


class IngestionReceipt(Base):
    # Adds atomic idempotency without deleting old duplicates or rebuilding tables.
    __tablename__ = "ingestion_receipts"
    key = Column(String, primary_key=True)
    assessed = Column(Boolean, nullable=False, default=False)


class RejectedMessage(Base):
    __tablename__ = "rejected_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    received_at = Column(UTCDateTime, nullable=False)
    path = Column(String, nullable=False)
    errors = Column(JSON, nullable=False)
