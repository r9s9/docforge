"""Analysis orchestration: ingest -> diff -> classify -> derive fields/rules.

Produces an AnalysisJob holding the proposed template intelligence that a user
reviews and edits before publishing a Template (see services/publish.py).

Two entry points:
  * ``analyze_documents`` — synchronous (tests, CLI, fast/heuristic path).
  * ``start_analysis`` + ``run_analysis_job`` — create a pending job and run it
    in the background, so slow LLM calls don't block the HTTP request.
"""

from __future__ import annotations

import logging
import math
import threading
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..ai.client import LLMCancelled
from ..ai_classifier import classify, derive_field_definitions, derive_validation_rules
from ..config import Settings, get_settings
from ..db.models import AnalysisJob, SourceDocument
from ..db.session import SessionLocal, engine
from ..document_ingest import extract_source_document
from ..jobs import clear_cancel, register_cancel
from ..multi_doc_differ import diff_documents, pick_representative
from ..logging_setup import log_event, reset_request_context, set_request_context
from ..schemas.enums import JobStatus
from ..schemas.extraction import DocumentExtraction
from .audit import record_decision

logger = logging.getLogger("docforge.analysis")


def _execute_analysis(
    db: Session,
    job: AnalysisJob,
    sources: list[SourceDocument],
    settings: Settings,
    report=None,
    cancel_event=None,
) -> None:
    """Run the pipeline and fill ``job`` (caller commits).

    ``report(pct:int, stage:str|None, force:bool)`` (optional) emits live progress.
    """
    def rp(pct, stage=None, force=False):
        if report:
            report(pct, stage, force)

    log_event(logger, "analysis.start", job=job.id, files=len(sources))
    rp(5, f"Extracting {len(sources)} document(s)…", True)
    extractions: list[DocumentExtraction] = []
    for i, sd in enumerate(sources):
        rec = extract_source_document(db, sd)
        ex = DocumentExtraction.model_validate(rec.extraction)
        extractions.append(ex)
        log_event(
            logger, "analysis.extracted", job=job.id, file=sd.filename,
            elements=len(ex.elements), top_level=len(ex.top_level_elements()),
            pages=ex.page_count,
        )
        rp(5 + int(20 * (i + 1) / max(1, len(sources))), force=True)

    rp(28, "Comparing documents…", True)
    diff = diff_documents(extractions) if len(extractions) >= 2 else None
    rep_index = pick_representative(extractions) if len(extractions) >= 2 else 0
    rep = extractions[rep_index]

    rp(35, "Classifying content…", True)

    # The classify call blocks (the AI can be slow and may not stream). A
    # heartbeat advances the bar 35->85 using the real streamed fraction when
    # available, else a time estimate — so the UI always shows live movement.
    # It is the SOLE progress writer during classify (separate DB connection),
    # so it never races the worker session.
    n_nodes = max(1, len(rep.top_level_elements()))
    shared = {"frac": None, "stage": "Classifying with AI…"}
    stop = threading.Event()

    def heartbeat():
        t0 = time.monotonic()
        tau = max(20.0, n_nodes * 2.0)  # time constant for the asymptotic creep
        while not stop.wait(1.2):
            frac = shared["frac"]
            if frac is None:  # no live tokens yet -> asymptotic time-based creep
                frac = min(0.92, 1.0 - math.exp(-(time.monotonic() - t0) / tau))
            pct = 35 + int(50 * max(0.0, min(1.0, frac)))
            try:
                with engine.connect() as conn:
                    conn.execute(
                        text(
                            "UPDATE analysis_jobs SET progress=:p, stage=:s "
                            "WHERE id=:id AND progress < :p"
                        ),
                        {"p": pct, "s": shared["stage"], "id": job.id},
                    )
                    conn.commit()
            except Exception:  # pragma: no cover - best effort heartbeat
                pass

    def cls_progress(detail, fraction):
        shared["frac"] = fraction
        shared["stage"] = detail

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    try:
        result = classify(
            rep, diff, settings=settings, on_progress=cls_progress, cancel_event=cancel_event
        )
    finally:
        stop.set()
        hb.join(timeout=2)

    # Count how the document broke down by classification — the key signal when
    # debugging "fields not recognized": how many nodes ended up fixed vs dynamic.
    from collections import Counter

    cls_counts = dict(Counter(c.classification.value for c in result.classifications))
    log_event(
        logger, "analysis.classified", job=job.id, engine=result.source,
        model=result.model_used or "heuristic", nodes=len(result.classifications),
        breakdown=";".join(f"{k}:{v}" for k, v in sorted(cls_counts.items())),
        ai_warning=bool(result.ai_warning),
    )

    rp(88, "Deriving fields & rules…", True)
    fields = derive_field_definitions(rep, result)
    rules = derive_validation_rules(fields)
    log_event(
        logger, "analysis.done", job=job.id, doc_type=result.document_type_guess,
        fields=len(fields), rules=len(rules),
    )

    job.representative_document_id = rep.document_id
    job.diff = diff.model_dump(mode="json") if diff else None
    job.classification = result.model_dump(mode="json")
    job.field_definitions = [f.model_dump(mode="json") for f in fields]
    job.validation_rules = [r.model_dump(mode="json") for r in rules]
    job.document_type_guess = result.document_type_guess
    job.model_used = result.model_used
    job.ai_warning = result.ai_warning
    job.status = JobStatus.COMPLETED.value

    record_decision(
        db,
        kind="classify",
        source=result.source,
        subject_type="analysis_job",
        subject_id=job.id,
        model_used=result.model_used,
        summary=(
            f"Analyzed {len(extractions)} document(s); "
            f"detected type '{result.document_type_guess}' with {len(fields)} field(s)."
        ),
        workspace_id=job.workspace_id,
    )


def analyze_documents(
    db: Session,
    sources: list[SourceDocument],
    *,
    settings: Settings | None = None,
    name: str | None = None,
    workspace_id: str | None = None,
) -> AnalysisJob:
    """Run the full analysis pipeline synchronously over 1–5 stored documents."""
    settings = settings or get_settings()
    if not sources:
        raise ValueError("at least one source document is required")
    if len(sources) > settings.max_files_per_analysis:
        raise ValueError(f"at most {settings.max_files_per_analysis} documents per analysis")

    job = AnalysisJob(
        status=JobStatus.RUNNING.value,
        name=name,
        source_document_ids=[s.id for s in sources],
        workspace_id=workspace_id,
    )
    db.add(job)
    db.flush()

    try:
        _execute_analysis(db, job, sources, settings)
    except Exception as exc:
        logger.exception("Analysis failed")
        job.status = JobStatus.FAILED.value
        job.error = str(exc)
        db.commit()
        raise

    db.commit()
    db.refresh(job)
    return job


def start_analysis(
    db: Session,
    sources: list[SourceDocument],
    *,
    settings: Settings | None = None,
    name: str | None = None,
    workspace_id: str | None = None,
    owner_id: str | None = None,
) -> AnalysisJob:
    """Create a PENDING analysis job (the work is run later by run_analysis_job)."""
    settings = settings or get_settings()
    if not sources:
        raise ValueError("at least one source document is required")
    if len(sources) > settings.max_files_per_analysis:
        raise ValueError(f"at most {settings.max_files_per_analysis} documents per analysis")

    job = AnalysisJob(
        status=JobStatus.PENDING.value,
        name=name,
        source_document_ids=[s.id for s in sources],
        workspace_id=workspace_id,
        owner_id=owner_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_analysis_job(job_id: str, settings: Settings | None = None) -> None:
    """Execute a pending analysis job in its own DB session (background-safe)."""
    settings = settings or get_settings()
    cancel_event = register_cancel(job_id)
    db = SessionLocal()
    # Attribute this background job's logs to the owning user + job, so they show
    # on that user's in-app Logs page (the request context doesn't cross threads).
    ctx_token = set_request_context(rid=f"job-{job_id[:8]}", user=None)
    try:
        job = db.get(AnalysisJob, job_id)
        if job is None:
            return
        set_request_context(rid=f"job-{job_id[:8]}", user=job.owner_id)
        # Cancelled while still queued -> stop before doing any work.
        if cancel_event.is_set():
            job.status = JobStatus.CANCELLED.value
            job.stage = "Cancelled"
            db.commit()
            return
        job.status = JobStatus.RUNNING.value
        job.progress = 2
        job.stage = "Starting…"
        db.commit()

        last_commit = [time.monotonic()]

        def report(pct: int, stage: str | None = None, force: bool = False) -> None:
            job.progress = max(0, min(100, int(pct)))
            if stage is not None:
                job.stage = stage
            now = time.monotonic()
            if force or now - last_commit[0] >= 0.5:  # throttle writes
                db.commit()
                last_commit[0] = now

        sources = [
            s for sid in (job.source_document_ids or []) if (s := db.get(SourceDocument, sid))
        ]
        # Resolve which AI key this user's action uses (own / free / global /
        # none) and run the whole pipeline under that plan so every LLM call
        # picks it up. Spend a free-tier credit only if the model actually ran.
        from ..ai_quota import increment_free_use, plan_ai_for_owner, use_ai_plan

        plan = plan_ai_for_owner(job.owner_id)
        with use_ai_plan(plan):
            _execute_analysis(db, job, sources, settings, report=report, cancel_event=cancel_event)
        if plan.counts_against_free and (job.classification or {}).get("source") == "llm":
            increment_free_use(job.owner_id)
        job.progress = 100
        job.stage = "Done"
        db.commit()
    except LLMCancelled:
        log_event(logger, "analysis.cancelled", job=job_id)
        try:
            job = db.get(AnalysisJob, job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED.value
                job.stage = "Cancelled"
                db.commit()
        except Exception:  # pragma: no cover - best effort
            pass
    except Exception as exc:
        logger.exception("Background analysis failed")
        log_event(logger, "analysis.failed", level=logging.ERROR, job=job_id,
                  error=f"{type(exc).__name__}: {str(exc)[:200]}")
        try:
            job = db.get(AnalysisJob, job_id)
            if job is not None:
                job.status = JobStatus.FAILED.value
                job.error = str(exc)
                db.commit()
        except Exception:  # pragma: no cover - best effort
            pass
    finally:
        clear_cancel(job_id)
        db.close()
        reset_request_context(ctx_token)
