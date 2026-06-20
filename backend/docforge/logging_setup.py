"""Logging configuration + structured event logging (spec §19: privacy-aware).

DocForge logs *metadata* (ids, counts, statuses, timings) and never document
text. Two facilities live here:

  * ``configure_logging`` — console + optional rotating file handler, with a
    request-correlation id attached to every line.
  * ``log_event`` — a tiny structured logger: ``event=<name> rid=<id> k=v …``.
    Used for every API action and every AI call so a single request can be
    traced end to end (the request middleware stamps the ``rid``; AI calls and
    services emitting events inherit it automatically).
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from collections import deque
from contextvars import ContextVar

from .config import get_settings

_configured = False

# Per-request context (set by the API middleware). Carries a short correlation
# id + who/what so downstream logs (AI calls, services) can reference them.
_request_ctx: ContextVar[dict] = ContextVar("docforge_request_ctx", default={})


def set_request_context(**fields) -> object:
    """Replace the current request context; returns a token for ``reset``."""
    return _request_ctx.set(dict(fields))


def update_request_context(**fields) -> None:
    """Merge fields into the current request context (e.g. add the user id)."""
    cur = dict(_request_ctx.get())
    cur.update(fields)
    _request_ctx.set(cur)


def reset_request_context(token: object) -> None:
    try:
        _request_ctx.reset(token)  # type: ignore[arg-type]
    except (ValueError, LookupError):
        pass


def current_rid() -> str | None:
    return _request_ctx.get().get("rid")


def redact(text: str, *, keep: int = 12) -> str:
    """Return a redacted preview of potentially sensitive text."""
    settings = get_settings()
    if not text:
        return ""
    if not settings.log_redact:
        return text
    head = text[:keep]
    return f"{head}…[redacted {len(text) - keep} chars]" if len(text) > keep else "…[redacted]"


def _fmt_value(v: object) -> str:
    """Render a field value compactly; quote only when it contains spaces."""
    s = "true" if v is True else "false" if v is False else "" if v is None else str(v)
    return f'"{s}"' if (" " in s or "=" in s) else s


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields) -> None:
    """Emit one structured line: ``event=<event> rid=<id> key=value …``.

    The request correlation id (and any user id) from the current context is
    prepended automatically, so logs from middleware, services and AI calls all
    share the same ``rid`` and can be grepped together.
    """
    ctx = _request_ctx.get()
    parts = [f"event={event}"]
    if ctx.get("rid"):
        parts.append(f"rid={ctx['rid']}")
    if ctx.get("user"):
        parts.append(f"user={ctx['user']}")
    for k, v in fields.items():
        parts.append(f"{k}={_fmt_value(v)}")
    logger.log(level, " ".join(parts))


# --- In-app log buffer (per-user, for the Logs page) ----------------------
# A bounded in-memory ring of recent records, each tagged with the rid/user that
# was active when it was emitted, so the app can show each user their own logs.
# Process-local and ephemeral (cleared on restart) — a troubleshooting aid, not
# an audit store.
_LOG_BUFFER: deque[dict] = deque(maxlen=4000)


class _ContextFilter(logging.Filter):
    """Attach the current request rid/user to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _request_ctx.get()
        record.rid = ctx.get("rid")  # type: ignore[attr-defined]
        record.user = ctx.get("user")  # type: ignore[attr-defined]
        return True


class _BufferHandler(logging.Handler):
    """Store rendered records in the ring buffer for the in-app Logs page."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _LOG_BUFFER.append(
                {
                    "ts": record.created,
                    "time": time.strftime("%H:%M:%S", time.localtime(record.created)),
                    "level": record.levelname,
                    "logger": record.name,
                    "rid": getattr(record, "rid", None),
                    "user": getattr(record, "user", None),
                    "message": record.getMessage(),
                }
            )
        except Exception:  # logging must never raise
            pass


def recent_logs(user_id: str | None, *, limit: int = 300) -> list[dict]:
    """Recent log entries attributed to ``user_id`` (newest last)."""
    items = [e for e in _LOG_BUFFER if e.get("user") == user_id]
    return items[-limit:]


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)
    # Reset handlers so re-running (tests, reload) doesn't double-log.
    for h in list(root.handlers):
        root.removeHandler(h)

    ctx_filter = _ContextFilter()
    formatter = logging.Formatter(fmt, datefmt=datefmt)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(ctx_filter)
    root.addHandler(console)

    # In-app per-user log buffer (powers the Logs page).
    buffer = _BufferHandler()
    buffer.addFilter(ctx_filter)
    buffer.setLevel(logging.INFO)
    root.addHandler(buffer)

    if settings.log_file:
        try:
            fileh = logging.handlers.RotatingFileHandler(
                settings.log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
            )
            fileh.setFormatter(formatter)
            root.addHandler(fileh)
        except OSError:  # bad path / permissions — keep console logging
            logging.getLogger("docforge").warning(
                "could not open log file %s; logging to console only", settings.log_file
            )

    # Quiet the noisy access logger from uvicorn (our middleware logs requests).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True
