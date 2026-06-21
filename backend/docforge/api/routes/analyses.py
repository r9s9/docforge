"""Analysis-job endpoints (review screen + polling)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...db.models import AnalysisJob
from ...jobs import request_cancel
from ...schemas.enums import JobStatus
from ...services import build_job_preview_docx
from ..auth import CurrentUser, get_current_user
from ..deps import get_db
from ..schemas import PreviewDocxRequest
from ..serializers import analysis_job_dto

router = APIRouter(tags=["analyses"])

_TERMINAL = {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _get_job(db: Session, job_id: str, user: CurrentUser) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None or job.owner_id != user.id:
        raise HTTPException(status_code=404, detail="analysis job not found")
    return job


@router.get("/analyses/{job_id}")
def get_analysis(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    job = _get_job(db, job_id, user)
    return analysis_job_dto(job, db)


@router.post("/analyses/{job_id}/cancel")
def cancel_analysis(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Signal a running/pending analysis job to stop.

    Sets the job's cancellation Event, which the LLM client checks between
    streamed chunks — closing the connection so the model server stops
    generating. Already-finished jobs are returned unchanged.
    """
    job = _get_job(db, job_id, user)
    if job.status not in _TERMINAL:
        request_cancel(job_id)
        # If the worker hasn't picked it up yet, reflect intent immediately; the
        # runner will confirm CANCELLED when it observes the event.
        if job.status == JobStatus.PENDING.value:
            job.status = JobStatus.CANCELLED.value
            job.stage = "Cancelled"
            db.commit()
            db.refresh(job)
    return analysis_job_dto(job, db)


@router.post("/analyses/{job_id}/preview.docx")
def preview_analysis_docx(
    job_id: str,
    req: PreviewDocxRequest | None = None,
    mode: str = "filled",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Build the proposed template as a real DOCX for the review screen.

    ``mode=filled`` renders readable «Label» sample values; ``mode=tags`` returns
    the raw template with visible Jinja placeholders. Optional body carries the
    user's in-progress field/classification edits so the preview stays in sync.
    """
    job = _get_job(db, job_id, user)
    if mode not in ("filled", "tags"):
        raise HTTPException(status_code=400, detail="mode must be 'filled' or 'tags'")
    req = req or PreviewDocxRequest()
    try:
        data = build_job_preview_docx(
            db, job, mode=mode, fields=req.fields, classifications=req.classifications
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # e.g. a Jinja TemplateSyntaxError from a bad field name
        # Put the real error TYPE + MESSAGE in the log line itself so it shows on
        # the in-app Logs page (which lists messages, not tracebacks), then keep
        # exc_info for the full traceback in the console/file logs.
        logging.getLogger("docforge.api.analyses").error(
            "preview.docx build failed (mode=%s): %s: %s",
            mode, type(exc).__name__, exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail=f"Preview build failed: {type(exc).__name__}: {exc}"
        ) from exc
    return Response(content=data, media_type=DOCX_MEDIA)
