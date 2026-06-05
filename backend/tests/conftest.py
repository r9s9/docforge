"""Shared pytest fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import docforge.db.models  # noqa: F401 — register tables on the metadata
from docforge.config import get_settings
from docforge.db.base import Base
from docforge.sampledata import write_all


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Hermetic tests: every test gets a fresh data dir so it never reads the
    developer's local ``app_settings.json`` (which could enable a slow LLM).
    Keeps AI inactive (heuristic) unless a test explicitly configures it.
    """
    s = get_settings()
    monkeypatch.setattr(s, "data_dir", tmp_path / "data")
    s.ensure_dirs()
    yield


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    """All six sample DOCX files (3 types x 2 variants), generated once."""
    d = tmp_path_factory.mktemp("samples")
    write_all(d)
    return d


@pytest.fixture
def project_docs(sample_dir):
    return [sample_dir / "project_report_1.docx", sample_dir / "project_report_2.docx"]


@pytest.fixture
def invoice_docs(sample_dir):
    return [sample_dir / "invoice_1.docx", sample_dir / "invoice_2.docx"]


@pytest.fixture
def compliance_docs(sample_dir):
    return [sample_dir / "compliance_report_1.docx", sample_dir / "compliance_report_2.docx"]


@pytest.fixture
def settings_tmp(tmp_path, monkeypatch):
    """Point the cached settings at an isolated temp data dir."""
    s = get_settings()
    monkeypatch.setattr(s, "data_dir", tmp_path / "data")
    s.ensure_dirs()
    return s


@pytest.fixture
def db_session(tmp_path):
    """An isolated SQLite session with all tables created."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestSession()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
