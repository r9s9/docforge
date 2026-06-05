"""SQLAlchemy declarative base + shared mixins (UUID PK, timestamps)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def new_uuid() -> str:
    """32-char hex UUID4 — used as the primary key for every entity."""
    return uuid.uuid4().hex


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
