"""Audit-trail helper for AI decisions and template publication (spec §19)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.models import AIDecisionLog


def record_decision(
    db: Session,
    *,
    kind: str,
    source: str,
    subject_type: str | None = None,
    subject_id: str | None = None,
    model_used: str | None = None,
    summary: str | None = None,
    payload: dict | None = None,
    workspace_id: str | None = None,
    owner_id: str | None = None,
    commit: bool = False,
) -> AIDecisionLog:
    """Append an audit entry. Caller controls the surrounding transaction."""
    log = AIDecisionLog(
        kind=kind,
        source=source,
        subject_type=subject_type,
        subject_id=subject_id,
        model_used=model_used,
        summary=summary,
        payload=payload,
        workspace_id=workspace_id,
        owner_id=owner_id,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    return log
