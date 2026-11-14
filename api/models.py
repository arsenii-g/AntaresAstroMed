from sqlalchemy import Column, Integer, String, DateTime, JSON
from .database import Base

class TelemetryModel(Base):
    __tablename__ = "telemetry"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String, index=True)
    ts = Column(DateTime, index=True)
    met_s = Column(Integer)
    crew_id = Column(String, index=True, nullable=True)
    payload_data = Column(JSON)

class EventModel(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String, index=True)
    ts = Column(DateTime, index=True)
    crew_id = Column(String, index=True, nullable=True)
    type = Column(String, index=True)
    severity = Column(String)
    payload_data = Column(JSON)

class CheckModel(Base):
    __tablename__ = "checks"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    crew_id = Column(String, index=True)
    ts = Column(DateTime, index=True)
    payload_data = Column(JSON)

class AssessmentModel(Base):
    __tablename__ = "assessments"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    crew_id = Column(String, index=True)
    ts = Column(DateTime, index=True)
    overall_level = Column(Integer)
    payload_data = Column(JSON)