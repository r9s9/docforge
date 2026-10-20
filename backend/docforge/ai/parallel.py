"""Run independent AI calls at the same time.

Template analysis makes many model calls that do not depend on each other:
one classify call per batch of elements, one description call per batch of
fields. Made one after another, a 100 KB document needed a dozen or more
calls in a row, which ran past a serverless host's request limit (Vercel
stops a request at 300 s at most). Run together, they take about as long as
the slowest one.

Each call runs in a copy of the caller's context, so everything a call reads
from context travels with it: the AI plan chosen for the user, the usage
accumulator, the request's log ids and the request's time budget.

Local model servers (Ollama, LM Studio) answer one request at a time, so for
them the calls stay sequential: queued requests would only spend their
timeouts waiting.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar
from urllib.parse import urlparse

from ..config import get_settings
from .errors import LLMCancelled

T = TypeVar("T")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def _is_local(base_url: str) -> bool:
    host = (urlparse(base_url or "").hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".local") or host.endswith(".localhost")


def slots_for(base_url: str) -> int:
    """How many calls to run at once against ``base_url``."""
    if _is_local(base_url):
        return 1
    return max(1, int(get_settings().ai_max_parallel_calls))


def slots_for_client(client) -> int:
    """How many calls to run at once through ``client`` (1 when it has no endpoint)."""
    base_url = getattr(getattr(client, "config", None), "base_url", "") or ""
    return slots_for(base_url) if base_url else 1


def run_all(
    tasks: list[Callable[[], T]],
    *,
    slots: int,
    on_done: Callable[[int, int], None] | None = None,
) -> list[T]:
    """Run ``tasks`` with up to ``slots`` at once; return results in task order.

    ``on_done(finished, total)`` is called from the calling thread as each task
    completes (safe for progress callbacks that write to the database). If any
    task fails, the error is raised once all tasks have stopped: a cancellation
    first, otherwise the error of the earliest failed task.
    """
    if not tasks:
        return []
    if slots <= 1 or len(tasks) == 1:
        out = []
        for i, task in enumerate(tasks):
            out.append(task())
            if on_done is not None:
                on_done(i + 1, len(tasks))
        return out

    results: list = [None] * len(tasks)
    errors: dict[int, BaseException] = {}
    with ThreadPoolExecutor(max_workers=min(slots, len(tasks))) as pool:
        futures = {
            pool.submit(contextvars.copy_context().run, task): i for i, task in enumerate(tasks)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            i = futures[future]
            try:
                results[i] = future.result()
            except BaseException as exc:  # re-raised below, after the others stop
                errors[i] = exc
            if on_done is not None:
                on_done(done, len(tasks))
    if errors:
        for exc in errors.values():
            if isinstance(exc, LLMCancelled):
                raise exc
        raise errors[min(errors)]
    return results
