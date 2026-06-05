"""Startup recovery for jobs orphaned by a crash/restart.

The in-process job runner (``jobs.py``) is not durable: if the server stops
mid-run, an AnalysisJob/GenerationRequest is left in ``pending``/``running``
forever. On startup we mark those as failed so nothing is stuck and the UI can
surface a clear error instead of polling indefinitely.
"""

from __future__ import annotations

import logging

from ..db.models import AnalysisJob, GenerationRequest
from ..db.session import SessionLocal
from ..schemas.enums import JobStatus

logger = logging.getLogger("docforge.recovery")

_ACTIVE = (JobStatus.PENDING.value, JobStatus.RUNNING.value)


def recover_stuck_jobs(db=None) -> int:
    """Mark orphaned active jobs as failed. Returns how many were recovered.

    Opens its own session when ``db`` is not supplied (the startup case).
    """
    own = db is None
    db = db or SessionLocal()
    recovered = 0
    try:
        for model in (AnalysisJob, GenerationRequest):
            stuck = db.query(model).filter(model.status.in_(_ACTIVE)).all()
            for job in stuck:
                job.status = JobStatus.FAILED.value
                if hasattr(job, "error"):
                    job.error = "Interrupted by a server restart."
                recovered += 1
        if recovered:
            db.commit()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Job recovery failed")
        db.rollback()
    finally:
        if own:
            db.close()
    return recovered
