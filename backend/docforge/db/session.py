"""Database engine / session setup.

Defaults to local SQLite (local-first). ``init_db`` uses ``create_all`` for a
zero-config dev experience; Alembic migrations are provided for the enterprise
path (see ``backend/alembic``).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from ..config import get_settings
from .base import Base

_settings = get_settings()


def database_url_with_driver(url: str) -> str:
    """Name the Postgres driver explicitly when the URL leaves it implicit.

    A bare ``postgresql://`` URL means "SQLAlchemy's default driver", and that
    default changed: SQLAlchemy 2.0 picked psycopg2, 2.1 picks psycopg 3. The
    deployment installs psycopg2-binary, so a fresh build that pulled 2.1 failed
    to import the app at all, and every request crashed. Pinning the driver here
    makes the URL mean the same thing on every SQLAlchemy version. The Heroku
    style ``postgres://`` scheme, which SQLAlchemy rejects, is accepted too.
    """
    for bare in ("postgresql://", "postgres://"):
        if url.startswith(bare):
            return "postgresql+psycopg2://" + url[len(bare):]
    return url


if _settings.database_url.startswith("sqlite"):
    engine = create_engine(
        _settings.database_url, connect_args={"check_same_thread": False}, future=True
    )
else:
    # On serverless, many short-lived instances each hold their own engine, so a
    # persistent pool would pile up idle/stale connections against the database
    # (or its PgBouncer pooler). NullPool opens a fresh connection per checkout
    # and closes it on return; pre_ping discards any connection a frozen instance
    # left half-dead. Pair this with Supabase's *transaction* pooler (port 6543).
    engine = create_engine(
        database_url_with_driver(_settings.database_url),
        poolclass=NullPool,
        pool_pre_ping=True,
        future=True,
    )
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
