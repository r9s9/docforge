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
