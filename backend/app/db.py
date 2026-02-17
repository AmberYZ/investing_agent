from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.settings import settings

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # timeout: seconds to wait when DB is locked (API + worker + threads contend; 60s reduces lock errors)
    _connect_args = {"check_same_thread": False, "timeout": 60}

# SQLite: use NullPool to avoid pool exhaustion (each request gets a new connection).
# PostgreSQL/MySQL: use a larger pool so concurrent requests (e.g. themes + N×metrics) don't time out.
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args=_connect_args,
        poolclass=NullPool,
    )
else:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=20,
        pool_recycle=300,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    elif engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

