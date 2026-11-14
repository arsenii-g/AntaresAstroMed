from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./spacehealth.db"

# Timeout de 30 segundos y check_same_thread para FastAPI
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"timeout": 30}
)

# Forzar modo WAL (Write-Ahead Logging) en SQLite para evitar bloqueos por concurrencia
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()