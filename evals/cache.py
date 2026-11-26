"""Record and replay model responses at the HTTP transport (DESIGN.md §6.2).

The cache wraps ``handle_request`` of two transport classes, in memory, inside the eval process:

- ``httpx.HTTPTransport``, which DocForge's OpenAI-compatible path uses (LM Studio and others)
- ``httpx2.HTTPTransport``, which the Anthropic SDK uses (Claude)

Every model call passes through one of them, so DocForge's own request building, parsing,
retries and fallbacks run unchanged on a replayed response, and its usage accounting sees the
original token counts.

Key: sha256 over the config, the case and its repeat, the method, the URL path and the request
body as canonical JSON (sorted keys, 32-hex IDs masked). Headers never enter the key and are
never stored, so neither an API key nor an organisation ID reaches the cache. Only successful
(2xx) responses are stored. Streamed answers are read whole first, so they're cached whole.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.scope import current_case

_HEX_ID = re.compile(r"\b[0-9a-f]{32}\b")
# Response headers worth keeping: how to parse the body, and retry hints. Nothing identifying.
_KEEP_HEADERS = frozenset({"content-type", "retry-after", "x-should-retry"})


def _transport_modules() -> list[Any]:
    modules = []
    for name in ("httpx", "httpx2"):
        try:
            modules.append(__import__(name))
        except ImportError:  # httpx2 comes with the Anthropic SDK; it may be absent
            continue
    return modules


def canonical_body(content: bytes) -> str:
    """A request body as canonical text: JSON with sorted keys, 32-hex IDs masked."""
    try:
        text = json.dumps(
            json.loads(content), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    except (ValueError, UnicodeDecodeError):
        text = content.decode("utf-8", "replace")
    return _HEX_ID.sub("<id>", text)


@dataclass
class CaseStats:
    """What the cache did for one case (and repeat)."""

    live_calls: int = 0
    replayed_calls: int = 0
    live_ms: float = 0.0  # time spent in calls that went to the network
    recorded_ms: float = 0.0  # what the replayed calls took when they were recorded
    replay_ms: float = 0.0  # time spent serving replays


class ResponseCache:
    """Record/replay for one config. ``refresh=True`` (``--no-cache``) always calls live."""

    def __init__(self, root: Path, config_name: str, *, refresh: bool = False):
        self.config_name = config_name
        self.dir = Path(root) / config_name
        self.refresh = refresh
        self._stats: dict[tuple[str, int], CaseStats] = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self._originals: list[tuple[Any, Any]] = []

    # --- installation --------------------------------------------------------------------

    def install(self) -> None:
        """Wrap the transports' ``handle_request`` (in memory, this process only)."""
        if self._originals:
            return
        for module in _transport_modules():
            original = module.HTTPTransport.handle_request

            def handle_request(transport, request, _original=original, _module=module):
                return self._handle(_module, _original, transport, request)

            module.HTTPTransport.handle_request = handle_request
            self._originals.append((module, original))

    def uninstall(self) -> None:
        """Put the original ``handle_request`` methods back."""
        for module, original in reversed(self._originals):
            module.HTTPTransport.handle_request = original
        self._originals.clear()

    # --- reading the results -------------------------------------------------------------

    def stats(self, case_id: str, repeat: int = 0) -> CaseStats:
        """The cache's counters for one case."""
        with self._lock:
            return self._stats.get((case_id, repeat), CaseStats())

    def totals(self) -> CaseStats:
        """The counters summed over every case."""
        total = CaseStats()
        with self._lock:
            for stats in self._stats.values():
                total.live_calls += stats.live_calls
                total.replayed_calls += stats.replayed_calls
                total.live_ms += stats.live_ms
                total.recorded_ms += stats.recorded_ms
                total.replay_ms += stats.replay_ms
        return total

    def last_call_live(self) -> bool:
        """Whether this thread's most recent model call went to the network."""
        return getattr(self._local, "live", True)

    # --- the mechanism -------------------------------------------------------------------

    def key(self, request) -> str:
        """The cache key of a request made inside the current case."""
        case_id, repeat = current_case()
        material = json.dumps(
            [self.config_name, case_id, repeat, request.method, request.url.path,
             canonical_body(request.content)],
            ensure_ascii=False,
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def path_for(self, key: str) -> Path:
        """Where the entry for ``key`` is stored."""
        return self.dir / key[:2] / f"{key}.json.gz"

    def _count(self, scope: tuple[str, int], **amounts: float) -> None:
        with self._lock:
            stats = self._stats.setdefault(scope, CaseStats())
            for name, amount in amounts.items():
                setattr(stats, name, getattr(stats, name) + amount)

    def _handle(self, module, original, transport, request):
        if request.method != "POST":  # model calls are POSTs; anything else passes through
            return original(transport, request)
        scope = current_case()
        path = self.path_for(self.key(request))
        if not self.refresh and path.exists():
            started = time.perf_counter()
            entry = json.loads(gzip.decompress(path.read_bytes()))
            response = module.Response(
                entry["status"], headers=entry["headers"],
                content=base64.b64decode(entry["body"]), request=request,
            )
            self._count(scope, replayed_calls=1, recorded_ms=entry["live_ms"],
                        replay_ms=(time.perf_counter() - started) * 1000)
            self._local.live = False
            return response

        started = time.perf_counter()
        upstream = original(transport, request)
        try:
            body = upstream.read()  # the whole answer, streamed or not (and decoded)
        finally:
            upstream.close()
        live_ms = (time.perf_counter() - started) * 1000
        headers = [(k, v) for k, v in upstream.headers.multi_items() if k.lower() in _KEEP_HEADERS]
        if 200 <= upstream.status_code < 300:
            self._write(path, {
                "status": upstream.status_code,
                "headers": headers,
                "body": base64.b64encode(body).decode("ascii"),
                "live_ms": round(live_ms, 1),
                "path": request.url.path,
                "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            })
        self._count(scope, live_calls=1, live_ms=live_ms)
        self._local.live = True
        return module.Response(upstream.status_code, headers=headers, content=body,
                               request=request)

    @staticmethod
    def _write(path: Path, entry: dict[str, Any]) -> None:
        """Write an entry atomically: parallel calls may finish at the same moment."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = gzip.compress(json.dumps(entry, ensure_ascii=False).encode("utf-8"), mtime=0)
        handle, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp, path)
