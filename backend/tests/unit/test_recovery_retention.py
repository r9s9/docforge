"""Tests for startup job recovery and generated-file retention."""

from __future__ import annotations

import os
import time

from docforge.db.models import AnalysisJob, GenerationRequest
from docforge.services.recovery import recover_stuck_jobs
from docforge.services.retention import prune_generated


def test_recover_stuck_jobs(db_session):
    job = AnalysisJob(status="running", source_document_ids=[])
    gen = GenerationRequest(template_id="t", version=1, status="pending")
    db_session.add_all([job, gen])
    db_session.commit()

    recovered = recover_stuck_jobs(db_session)
    assert recovered == 2

    db_session.refresh(job)
    db_session.refresh(gen)
    assert job.status == "failed"
    assert gen.status == "failed"
    assert "restart" in (job.error or "").lower()


def test_recover_leaves_finished_jobs(db_session):
    done = AnalysisJob(status="completed", source_document_ids=[])
    db_session.add(done)
    db_session.commit()
    assert recover_stuck_jobs(db_session) == 0
    db_session.refresh(done)
    assert done.status == "completed"


def test_prune_generated_by_age(settings_tmp, monkeypatch):
    monkeypatch.setattr(settings_tmp, "generated_retention_days", 1)
    gdir = settings_tmp.generated_dir
    old = gdir / "old.docx"
    old.write_bytes(b"x" * 10)
    fresh = gdir / "fresh.docx"
    fresh.write_bytes(b"y" * 10)
    past = time.time() - 3 * 86400
    os.utime(old, (past, past))

    removed = prune_generated(settings_tmp)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_prune_generated_by_size(settings_tmp, monkeypatch):
    monkeypatch.setattr(settings_tmp, "generated_retention_days", 3650)  # disable age
    monkeypatch.setattr(settings_tmp, "generated_max_total_mb", 1)
    gdir = settings_tmp.generated_dir
    older = gdir / "a.docx"
    older.write_bytes(b"0" * (700 * 1024))
    newer = gdir / "b.docx"
    newer.write_bytes(b"0" * (700 * 1024))
    os.utime(older, (time.time() - 500, time.time() - 500))  # a is oldest

    removed = prune_generated(settings_tmp)  # total ~1.37MB > 1MB cap
    assert removed >= 1
    assert not older.exists()  # oldest pruned first
    assert newer.exists()
