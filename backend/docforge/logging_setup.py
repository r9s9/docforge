"""Logging configuration (spec §19: privacy-aware logging).

DocForge deliberately logs *metadata* (ids, counts, statuses) and never document
text. ``redact`` is provided as a safety net for any future call site that might
otherwise include user content in a log line.
"""

from __future__ import annotations

import logging

from .config import get_settings

_configured = False


def redact(text: str, *, keep: int = 12) -> str:
    """Return a redacted preview of potentially sensitive text."""
    settings = get_settings()
    if not text:
        return ""
    if not settings.log_redact:
        return text
    head = text[:keep]
    return f"{head}…[redacted {len(text) - keep} chars]" if len(text) > keep else "…[redacted]"


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _configured = True
