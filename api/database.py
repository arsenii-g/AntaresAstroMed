"""UTC-safe SQLite persistence, including databases written by the first API."""
from datetime import timezone
from fastapi import Request
from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("A timezone-aware datetime is required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


def make_engine(url):
    if not url.startswith("sqlite:"):
        raise ValueError("This prototype uses SQLite")
    options = {"connect_args": {"timeout": 1, "check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        options["poolclass"] = StaticPool
    engine = create_engine(url, **options)

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def get_db(request: Request):
    with request.app.state.session_factory() as session:
        yield session
