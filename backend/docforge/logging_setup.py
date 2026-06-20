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

    formatter = logging.Formatter(fmt, datefmt=datefmt)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

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
