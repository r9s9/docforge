"""A time budget for the AI work done inside one request.

On a serverless host the platform stops a request at a fixed limit (Vercel: at
most 300 s) and answers with a bare 504 the browser cannot read, so the user
sees "network error" and loses the whole analysis. Work that runs inside a
request therefore gets a budget here, a little under the platform limit. The
AI client gives each call only the time that is left and refuses new calls
once too little remains; every step already treats that like any other
unavailable model and carries on with the deterministic engine, so the
request still returns a finished result in time.

Kept in a ``ContextVar`` so it follows the request into nested clients and
into the worker threads of :mod:`docforge.ai.parallel` (which copy the
caller's context).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from contextvars import ContextVar

from .errors import LLMUnavailable

# A call given less than this is not worth starting: it would only time out.
MIN_CALL_SECONDS = 8.0

_deadline: ContextVar[float | None] = ContextVar("docforge_ai_deadline", default=None)


@contextlib.contextmanager
def time_budget(seconds: float | None) -> Iterator[None]:
    """Limit the AI work inside the block to ``seconds`` (None or 0: no limit).

    Nested budgets keep the earlier end, so an inner block can only tighten it.
    """
    if not seconds or seconds <= 0:
        yield
        return
    end = time.monotonic() + seconds
    current = _deadline.get()
    token = _deadline.set(end if current is None else min(current, end))
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining() -> float | None:
    """Seconds left in the current budget, or None when there is none."""
    end = _deadline.get()
    return None if end is None else end - time.monotonic()


def expired() -> bool:
    left = remaining()
    return left is not None and left <= 0


_OUT_OF_TIME = (
    "Out of time for AI on this request, so the rest was finished with the "
    "built-in engine."
)


def budgeted(timeout: float) -> float:
    """``timeout`` capped to what is left of the budget, for one model call.

    Raises :class:`LLMUnavailable` when too little is left for a useful call.
    """
    left = remaining()
    if left is None:
        return timeout
    if left < MIN_CALL_SECONDS:
        raise LLMUnavailable(_OUT_OF_TIME)
    return min(float(timeout), left)


def check() -> None:
    """Raise :class:`LLMUnavailable` once the budget is spent (mid-stream checks)."""
    if expired():
        raise LLMUnavailable(_OUT_OF_TIME)
