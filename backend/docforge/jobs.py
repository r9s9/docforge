"""Tiny in-process background job runner.

Long-running work (LLM analysis, generation) is offloaded here so HTTP requests
return immediately and the client polls for status. Local models can be slow —
a synchronous request that blocks for minutes will be dropped by proxies/browsers.

For a single-process deployment a thread pool is sufficient; swap for Celery/RQ
if you need multi-worker durability (the AnalysisJob/GenerationRequest rows
already model the state needed for that).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("docforge.jobs")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="docforge-job")


def submit(fn, *args, **kwargs):
    """Run ``fn`` in a background thread. Exceptions are logged, not raised."""

    def _wrapped():
        try:
            fn(*args, **kwargs)
        except Exception:  # pragma: no cover - defensive; jobs record their own failures
            logger.exception("Background job %s failed", getattr(fn, "__name__", fn))

    return _executor.submit(_wrapped)


# ---------------------------------------------------------------------------
# Cooperative cancellation
# ---------------------------------------------------------------------------
# A job registers a threading.Event when it starts; the cancel endpoint sets it.
# The LLM client checks the event between streamed chunks and aborts the HTTP
# connection — which makes the local model server (LM Studio) stop generating
# instead of running to completion after the user has navigated away.

_cancel_events: dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def register_cancel(job_id: str) -> threading.Event:
    """Create (or reuse) the cancellation Event for a job and return it."""
    with _cancel_lock:
        ev = _cancel_events.get(job_id)
        if ev is None:
            ev = threading.Event()
            _cancel_events[job_id] = ev
        return ev


def request_cancel(job_id: str) -> bool:
    """Signal a running job to stop. Returns True if a live job was signalled.

    If the job hasn't registered yet (still PENDING in the queue), we pre-create
    a *set* event so it cancels the instant it starts.
    """
    with _cancel_lock:
        ev = _cancel_events.get(job_id)
        if ev is None:
            ev = threading.Event()
            _cancel_events[job_id] = ev
            ev.set()
            return False
        ev.set()
        return True


def is_cancelled(job_id: str) -> bool:
    with _cancel_lock:
        ev = _cancel_events.get(job_id)
        return ev is not None and ev.is_set()


def clear_cancel(job_id: str) -> None:
    """Drop a job's cancellation Event once the job has finished."""
    with _cancel_lock:
        _cancel_events.pop(job_id, None)
