"""Watch DocForge's AI calls from inside the eval process (DESIGN.md §6.4).

In-memory wrappers only; no DocForge file changes. Each wrapper calls the original and records
what happened, without touching arguments or results:

- ``LLMClient.complete_agentic``, ``complete_json`` and ``complete``. One record per logical
  call: ``complete_agentic`` can fall back to ``complete_json`` internally, so only the outermost
  call is recorded. A record holds the call kind (the response schema's class name), the
  outcome (ok, or the exception that DocForge's fallback catches) and the time taken. When the
  schema is ``LLMComplianceJudgement``, the judge's verdicts are kept for the case.
- ``Usage.add``, DocForge's per-call usage accounting. Each call is priced with DocForge's own
  ``cost_for_call`` and counted as live or replayed, from what the response cache did.
"""

from __future__ import annotations

import functools
import threading
import time
from collections import defaultdict
from typing import Any

from evals.scope import current_case

JUDGE_SCHEMA = "LLMComplianceJudgement"


class CallObserver:
    """Records AI calls, judge verdicts and spend per case (and repeat)."""

    def __init__(self, cache=None):
        self.cache = cache
        self._calls: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        self._verdicts: dict[tuple[str, int], list[list[dict[str, Any]]]] = defaultdict(list)
        self._spend: dict[tuple[str, int], dict[str, float]] = defaultdict(
            lambda: {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
        )
        self._lock = threading.Lock()
        self._local = threading.local()
        self._originals: list[tuple[Any, str, Any]] = []

    # --- installation --------------------------------------------------------------------

    def install(self) -> None:
        """Wrap DocForge's call methods and usage accounting (this process only)."""
        if self._originals:
            return
        from docforge.ai.client import LLMClient
        from docforge.ai.usage import Usage

        for name in ("complete_agentic", "complete_json", "complete"):
            original = getattr(LLMClient, name)
            setattr(LLMClient, name, self._wrap_call(name, original))
            self._originals.append((LLMClient, name, original))
        original_add = Usage.add
        Usage.add = self._wrap_add(original_add)
        self._originals.append((Usage, "add", original_add))

    def uninstall(self) -> None:
        """Put the original methods back."""
        for owner, name, original in reversed(self._originals):
            setattr(owner, name, original)
        self._originals.clear()

    # --- reading the results -------------------------------------------------------------

    def calls(self, case_id: str, repeat: int = 0) -> list[dict[str, Any]]:
        """Every AI call made for a case, in order."""
        with self._lock:
            return list(self._calls.get((case_id, repeat), []))

    def verdicts(self, case_id: str, repeat: int = 0) -> list[list[dict[str, Any]]]:
        """The judge's verdict lists for a case, one per successful judge call."""
        with self._lock:
            return list(self._verdicts.get((case_id, repeat), []))

    def spend(self, case_id: str, repeat: int = 0) -> dict[str, float]:
        """Live and replayed cost of one case, in USD, and how many calls had no price."""
        with self._lock:
            return dict(self._spend.get((case_id, repeat), {"live": 0.0, "replayed": 0.0,
                                                             "unpriced_calls": 0}))

    def total_spend(self) -> dict[str, float]:
        """Live and replayed cost of the whole run so far."""
        total = {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
        with self._lock:
            for spend in self._spend.values():
                for key in total:
                    total[key] += spend[key]
        return total

    # --- the wrappers --------------------------------------------------------------------

    def _wrap_call(self, method: str, original):
        observer = self

        @functools.wraps(original)
        def wrapper(client, *args, **kwargs):
            if getattr(observer._local, "depth", 0):
                return original(client, *args, **kwargs)  # part of the outer call
            observer._local.depth = 1
            started = time.perf_counter()
            outcome, error, result = "ok", None, None
            try:
                result = original(client, *args, **kwargs)
                return result
            except BaseException as exc:
                outcome, error = "error", f"{type(exc).__name__}: {str(exc)[:160]}"
                raise
            finally:
                observer._local.depth = 0
                observer._record(method, client, kwargs, outcome, error, result, started)

        return wrapper

    def _record(self, method, client, kwargs, outcome, error, result, started) -> None:
        schema = kwargs.get("schema")
        kind = getattr(schema, "__name__", None) or method
        call: dict[str, Any] = {
            "kind": kind,
            "method": method,
            "model": getattr(getattr(client, "config", None), "model", None),
            "outcome": outcome,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if method == "complete_agentic":
            call["tier"] = kwargs.get("tier", "workhorse")
        if error:
            call["error"] = error
        scope = current_case()
        with self._lock:
            self._calls[scope].append(call)
            if outcome == "ok" and kind == JUDGE_SCHEMA and result is not None:
                self._verdicts[scope].append(
                    [verdict.model_dump(mode="json") for verdict in result.verdicts]
                )

    def _wrap_add(self, original):
        from docforge.ai.pricing import cost_for_call

        observer = self

        @functools.wraps(original)
        def add(usage, model, in_tokens, out_tokens, *, cache_read=0, cache_write=0):
            cost = cost_for_call(
                model, int(in_tokens or 0), int(out_tokens or 0),
                cache_read=int(cache_read or 0), cache_write=int(cache_write or 0),
            )
            live = observer.cache.last_call_live() if observer.cache is not None else True
            with observer._lock:
                spend = observer._spend[current_case()]
                if cost is None:
                    spend["unpriced_calls"] += 1
                else:
                    spend["live" if live else "replayed"] += cost
            return original(usage, model, in_tokens, out_tokens,
                            cache_read=cache_read, cache_write=cache_write)

        return add
