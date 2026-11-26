"""Which case (and which repeat of it) the current code is working on.

The runner sets it around each case; the response cache and the call observer read it, so a
model call is filed under the case that made it. It is a context variable, so DocForge's
parallel AI calls (``docforge.ai.parallel`` copies the caller's context) carry it too.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_CURRENT: ContextVar[tuple[str, int]] = ContextVar("evals_case", default=("", 0))


def current_case() -> tuple[str, int]:
    """(case ID, repeat index) of the case being run; ``("", 0)`` outside any case."""
    return _CURRENT.get()


@contextmanager
def case(case_id: str, repeat: int = 0) -> Iterator[None]:
    """Mark the code inside the block as working on ``case_id`` (repeat ``repeat``)."""
    token = _CURRENT.set((case_id, repeat))
    try:
        yield
    finally:
        _CURRENT.reset(token)
