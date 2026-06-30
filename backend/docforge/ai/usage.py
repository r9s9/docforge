"""Request/action-scoped AI token accounting.

Every ``LLMClient`` call reports its token usage via :func:`record_usage`. A
service wraps one user action (analyze / generate / compliance) in
:func:`track_usage`; the resulting :class:`Usage` is then persisted on the
action's record and surfaced to the UI so users can see exactly how many input
and output tokens an action spent (and a best-effort cost estimate).

Implemented with a ``ContextVar`` so deeply-nested clients contribute
transparently — no plumbing through every function signature. Do not nest
``track_usage`` for the same logical action (the inner scope shadows the outer).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field

from .pricing import cost_for_by_model


@dataclass
class Usage:
    in_tokens: int = 0
    out_tokens: int = 0
    calls: int = 0
    # model name -> {"in": int, "out": int, "calls": int}
    by_model: dict[str, dict] = field(default_factory=dict)

    def add(self, model: str | None, in_tokens: int | None, out_tokens: int | None) -> None:
        i, o = int(in_tokens or 0), int(out_tokens or 0)
        self.in_tokens += i
        self.out_tokens += o
        self.calls += 1
        m = self.by_model.setdefault(model or "?", {"in": 0, "out": 0, "calls": 0})
        m["in"] += i
        m["out"] += o
        m["calls"] += 1

    def as_dict(self) -> dict:
        """JSON-serialisable summary with a best-effort cost estimate."""
        return {
            "in": self.in_tokens,
            "out": self.out_tokens,
            "calls": self.calls,
            "cost_usd": cost_for_by_model(self.by_model),
            "by_model": self.by_model,
        }


_current: ContextVar[Usage | None] = ContextVar("docforge_ai_usage", default=None)


def record_usage(model: str | None, in_tokens: int | None, out_tokens: int | None) -> None:
    """Feed one call's usage into the active accumulator (no-op if none)."""
    acc = _current.get()
    if acc is not None:
        acc.add(model, in_tokens, out_tokens)


@contextlib.contextmanager
def track_usage() -> Iterator[Usage]:
    """Scope an accumulator over one action; yields the :class:`Usage` to read
    after the block (the object persists; only the ContextVar is reset)."""
    acc = Usage()
    token = _current.set(acc)
    try:
        yield acc
    finally:
        _current.reset(token)
