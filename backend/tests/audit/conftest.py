"""Audit test harness: every test runs against its own database and data dir.

The rest of the suite overrides ``get_db`` but leaves ``SessionLocal`` alone,
and several services open their own sessions with it (background analysis,
the free-tier counter, startup recovery). Those writes land in whatever
database the process was started with, which on a developer machine is the
real ``backend/data/docforge.db``. Here, every name bound to the engine or
session factory is repointed at a throwaway SQLite file, so an audit test can
exercise those paths without touching anyone's data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import docforge.db.models  # noqa: F401 — register tables
from docforge.api.app import app
from docforge.api.deps import get_db
from docforge.db.base import Base
from tests.audit.helpers import JWT_SECRET, token_for

# Modules that bind ``SessionLocal`` / ``engine`` at import time.
_BOUND = (
    "docforge.db.session",
    "docforge.api.deps",
    "docforge.services.analysis",
    "docforge.services.recovery",
)


@pytest.fixture
def audit_engine(tmp_path, monkeypatch, settings_tmp):
    import importlib

    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    for name in _BOUND:
        mod = importlib.import_module(name)
        if hasattr(mod, "SessionLocal"):
            monkeypatch.setattr(mod, "SessionLocal", factory)
        if hasattr(mod, "engine"):
            monkeypatch.setattr(mod, "engine", engine)
    yield engine
    engine.dispose()


@pytest.fixture
def audit_db(audit_engine):
    """A session on the same database the app's own sessions now use."""
    import docforge.db.session as s

    db = s.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def http(audit_engine, settings_tmp, monkeypatch):
    """A TestClient running the REAL JWT check, plus ``as_user(uid)`` headers.

    Nothing about authentication is stubbed: a test that says user B cannot
    reach user A's data is proving it against the production auth path.
    """
    monkeypatch.setattr(settings_tmp, "auth_required", True)
    monkeypatch.setattr(settings_tmp, "supabase_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings_tmp, "supabase_jwt_audience", "authenticated")

    import docforge.db.session as s

    def _db():
        db = s.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    client = TestClient(app, raise_server_exceptions=False)

    def as_user(uid: str) -> dict:
        return {"Authorization": f"Bearer {token_for(uid)}"}

    client.as_user = as_user  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
