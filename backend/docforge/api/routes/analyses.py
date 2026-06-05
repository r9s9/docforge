"""Analysis-job endpoints (review screen + polling)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db.models import AnalysisJob
from ..deps import get_db
from ..serializers import analysis_job_dto

router = APIRouter(tags=["analyses"])


@router.get("/analyses/{job_id}")
def get_analysis(job_id: str, db: Session = Depends(get_db)) -> dict:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis job not found")
    return analysis_job_dto(job, db)
