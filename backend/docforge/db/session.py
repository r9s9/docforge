"""Database engine / session setup.

Defaults to local SQLite (local-first). ``init_db`` uses ``create_all`` for a
zero-config dev experience; Alembic migrations are provided for the enterprise
path (see ``backend/alembic``).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings
from .base import Base

_settings = get_settings()

_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)
engine = create_engine(_settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def _ensure_columns() -> None:
    """Add columns that exist on the models but not yet in the DB.

    Lightweight, non-destructive dev migration for SQLite so adding a column to a
    model doesn't require dropping the database. (Production uses Alembic.)
    """
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            coltype = col.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {coltype}'))


def init_db() -> None:
    """Create data directories and all tables (idempotent)."""
    _settings.ensure_dirs()
    from . import models  # noqa: F401 — register models on the metadata

    Base.metadata.create_all(engine)
    _ensure_columns()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
