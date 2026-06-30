"""Feedback loop: capture the user's corrections and replay them as guidance.

When a user publishes a reviewed template, or edits routed/composed values, the
deltas between what the AI proposed and what the user kept are stored as
:class:`TemplateCorrection` rows keyed by ``owner_id`` + ``document_type``. On a
later action of the same type those corrections are rendered into a short
few-shot block injected into the prompt, so the agent adapts to each user's
conventions over time.

Everything here degrades gracefully: a missing table or a DB hiccup never breaks
the action that triggered it (learning is best-effort).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..db.models import TemplateCorrection

logger = logging.getLogger("docforge.learning")

# Cap how much learned guidance we inject, to bound prompt size/cost.
_MAX_FEWSHOT = 8


def record_correction(
    db: Session,
    *,
    owner_id: str | None,
    document_type: str | None,
    kind: str,
    summaries: list[str],
    payload: dict | None = None,
) -> None:
    """Persist a batch of human-readable correction ``summaries`` (best-effort).

    ``payload`` keeps the structured deltas for future analysis; ``summaries`` are
    the lines replayed into prompts. No-op when there is nothing to learn.
    """
    summaries = [s for s in (summaries or []) if s and s.strip()]
    if not owner_id or not summaries:
        return
    try:
        row = TemplateCorrection(
            owner_id=owner_id,
            document_type=(document_type or "").strip() or None,
            kind=kind,
            summary="\n".join(summaries[:50]),
            payload=payload or {"summaries": summaries[:50]},
        )
        db.add(row)
        db.flush()
        logger.info(
            "recorded %d %s correction(s) for %s / %s",
            len(summaries), kind, owner_id, document_type,
        )
    except Exception:  # never fail the publish/generate over learning
        logger.debug("failed to record corrections", exc_info=True)
        db.rollback()


def recent_corrections(
    db: Session,
    owner_id: str | None,
    document_type: str | None,
    *,
    kind: str,
    limit: int = 5,
) -> list[TemplateCorrection]:
    """Most recent stored corrections for this owner + document type + kind."""
    if not owner_id:
        return []
    try:
        q = db.query(TemplateCorrection).filter(
            TemplateCorrection.owner_id == owner_id,
            TemplateCorrection.kind == kind,
        )
        if document_type:
            q = q.filter(TemplateCorrection.document_type == document_type.strip())
        return q.order_by(TemplateCorrection.created_at.desc()).limit(max(1, limit)).all()
    except Exception:  # pragma: no cover - table may not exist yet
        logger.debug("failed to load corrections", exc_info=True)
        return []


def corrections_fewshot(
    db: Session,
    owner_id: str | None,
    document_type: str | None,
    *,
    kind: str,
    limit: int = 5,
) -> str:
    """A compact prompt block of learned conventions, or "" if none.

    Injected verbatim into the classify/route prompts. Lines come from the
    human-readable summaries captured at correction time.
    """
    rows = recent_corrections(db, owner_id, document_type, kind=kind, limit=limit)
    if not rows:
        return ""
    lines: list[str] = []
    for r in rows:
        for line in (r.summary or "").splitlines():
            line = line.strip(" -•\t")
            if line and line not in lines:
                lines.append(line)
            if len(lines) >= _MAX_FEWSHOT:
                break
        if len(lines) >= _MAX_FEWSHOT:
            break
    if not lines:
        return ""
    header = (
        "Learned conventions — this user previously corrected the AI on documents "
        "of this type. Apply these where they genuinely fit (do not force them):"
    )
    return header + "\n" + "\n".join(f"- {ln}" for ln in lines)
