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

from .pricing import cost_for_call


@dataclass
class Usage:
    # ``in_tokens`` is the whole prompt, cached parts included, so the figure
    # means the same thing whichever provider served the call.
    in_tokens: int = 0
    out_tokens: int = 0
    calls: int = 0
    cache_read: int = 0
    cache_write: int = 0
    # Priced per call, not from the totals: a model whose rate depends on the
    # prompt's length (Claude Haiku 5.5) cannot be priced from a sum.
    cost_usd: float = 0.0
    priced_calls: int = 0
    # model name -> {"in", "out", "calls", "cache_read", "cache_write"}
    by_model: dict[str, dict] = field(default_factory=dict)

    def add(
        self,
        model: str | None,
        in_tokens: int | None,
        out_tokens: int | None,
        *,
        cache_read: int | None = 0,
        cache_write: int | None = 0,
    ) -> None:
        i, o = int(in_tokens or 0), int(out_tokens or 0)
        cr, cw = int(cache_read or 0), int(cache_write or 0)
        prompt = i + cr + cw
        self.in_tokens += prompt
        self.out_tokens += o
        self.cache_read += cr
        self.cache_write += cw
        self.calls += 1
        m = self.by_model.setdefault(
            model or "?", {"in": 0, "out": 0, "calls": 0, "cache_read": 0, "cache_write": 0}
        )
        m["in"] += prompt
        m["out"] += o
        m["calls"] += 1
        m["cache_read"] = m.get("cache_read", 0) + cr
        m["cache_write"] = m.get("cache_write", 0) + cw
        cost = cost_for_call(model, i, o, cache_read=cr, cache_write=cw)
        if cost is not None:
            self.cost_usd += cost
            self.priced_calls += 1

    def as_dict(self) -> dict:
        """JSON-serialisable summary with a best-effort cost estimate."""
        return {
            "in": self.in_tokens,
            "out": self.out_tokens,
            "calls": self.calls,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
            # None only when no call ran on a priced model; unknown models
            # contribute nothing rather than hiding the total.
            "cost_usd": round(self.cost_usd, 6) if self.priced_calls else None,
            "by_model": self.by_model,
        }


_current: ContextVar[Usage | None] = ContextVar("docforge_ai_usage", default=None)


def record_usage(
    model: str | None,
    in_tokens: int | None,
    out_tokens: int | None,
    *,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
) -> None:
    """Feed one call's usage into the active accumulator (no-op if none).

    ``in_tokens`` is the uncached prompt; ``cache_read`` / ``cache_write`` are
    the cached parts, which providers that report them bill differently.
    """
    acc = _current.get()
    if acc is not None:
        acc.add(model, in_tokens, out_tokens, cache_read=cache_read, cache_write=cache_write)


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
