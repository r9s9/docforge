"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.session import SessionLocal
from ..template_registry import TemplateRegistry


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_settings_dep() -> Settings:
    return get_settings()


def get_registry() -> TemplateRegistry:
    return TemplateRegistry(get_settings().templates_dir)
