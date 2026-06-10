"""Per-user AI resolution, free-tier quota, and request-scoped plan selection.

DocForge serves three kinds of AI access, decided per user, per action:

  * **own**    — the user configured their own provider + API key (unlimited).
  * **free**   — a shared, server-side key the platform owner pays for (e.g. a
                 cheap Claude Haiku key). Each user gets ``free_ai_limit`` free
                 actions; the key is NEVER exposed to the client.
  * **global** — the legacy single shared ``DOCFORGE_AI_*`` key (used only when
                 the free tier is not configured — i.e. local dev / tests).
  * **none**   — no AI available -> the deterministic offline heuristic engine.

The chosen ``AIConfig`` is published into a ``ContextVar`` for the duration of an
AI action via :func:`use_ai_plan`; :func:`docforge.settings_store.get_ai_config`
reads it so every ``LLMClient`` built deep inside the pipeline transparently uses
the right key. After a *free* action that actually hit the model, the caller calls
:func:`increment_free_use` to spend one credit.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from dataclasses import dataclass

from .config import get_settings
from .settings_store import AIConfig

logger = logging.getLogger("docforge.ai_quota")

# Request/job-scoped AI config. None -> fall back to the global env/file config.
_planned: ContextVar[AIConfig | None] = ContextVar("docforge_planned_ai", default=None)


@dataclass
class AIPlan:
    config: AIConfig
    mode: str  # "own" | "free" | "global" | "none"

    @property
    def counts_against_free(self) -> bool:
        """A free-tier action consumes one credit (only when the model is hit)."""
        return self.mode == "free"


# --- DB helpers -----------------------------------------------------------

def _row(owner_id: str | None):
    """Load the UserAIConfig for ``owner_id`` (own short-lived session).

    Returns None on any DB error (e.g. the table not existing yet) so AI
    resolution degrades gracefully instead of failing the action.
    """
    if not owner_id:
        return None
    from .db.models import UserAIConfig
    from .db.session import SessionLocal

    db = SessionLocal()
    try:
        return db.get(UserAIConfig, owner_id)
    except Exception:  # pragma: no cover - defensive (missing table / DB hiccup)
        logger.debug("could not load UserAIConfig for %s", owner_id, exc_info=True)
        return None
    finally:
        db.close()


def _own_config(row, s) -> AIConfig:
    return AIConfig(
        provider=row.provider or "openai",
        enabled=True,
        base_url=(row.base_url or "").strip(),
        api_key=(row.api_key or "").strip(),
        model=row.model or "",
        timeout_seconds=s.ai_timeout_seconds,
        max_retries=s.ai_max_retries,
        max_output_tokens=s.ai_max_output_tokens,
        no_think=bool(row.no_think),
    )


def _free_config(s) -> AIConfig:
    return AIConfig(
        provider=s.free_ai_provider,
        enabled=True,
        base_url=(s.free_ai_base_url or "").strip(),
        api_key=(s.free_ai_api_key or "").strip(),
        model=s.free_ai_model,
        timeout_seconds=s.ai_timeout_seconds,
        max_retries=s.ai_max_retries,
        max_output_tokens=s.ai_max_output_tokens,
    )


def _has_own(row) -> bool:
    return bool(row and row.enabled and (row.api_key or "").strip())


def _free_configured(s) -> bool:
    return bool(s.free_ai_enabled and (s.free_ai_api_key or "").strip())


# --- Planning -------------------------------------------------------------

def plan_ai_for_owner(owner_id: str | None, *, allow_free: bool = True) -> AIPlan:
    """Decide which AI path ``owner_id`` gets for one action (no mutation).

    ``allow_free=False`` is used for *previews* — they must never spend the shared
    key — so a non-own-key user falls back to the offline engine for previews
    while still being able to spend a real credit on the actual generate/analyze.
    """
    s = get_settings()
    row = _row(owner_id)

    if _has_own(row):
        return AIPlan(_own_config(row, s), "own")

    if _free_configured(s):
        # Free tier is the active model for users without their own key. The
        # legacy global key is intentionally bypassed here.
        if allow_free and (row.free_used if row else 0) < s.free_ai_limit:
            return AIPlan(_free_config(s), "free")
        return AIPlan(AIConfig(enabled=False), "none")

    # No free tier configured -> legacy behaviour: the global env/file config.
    from .settings_store import global_ai_config

    glob = global_ai_config()
    return AIPlan(glob, "global" if glob.active else "none")


@contextlib.contextmanager
def use_ai_plan(plan: AIPlan):
    """Publish ``plan.config`` so nested ``get_ai_config()`` calls resolve to it."""
    token = _planned.set(plan.config)
    try:
        yield
    finally:
        _planned.reset(token)


def planned_ai_config() -> AIConfig | None:
    """The request/job-scoped AIConfig, or None to use the global config."""
    return _planned.get()


# --- Quota accounting -----------------------------------------------------

def increment_free_use(owner_id: str | None) -> None:
    """Spend one free-tier credit for ``owner_id`` (creates the row if needed)."""
    if not owner_id:
        return
    from .db.models import UserAIConfig
    from .db.session import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(UserAIConfig, owner_id)
        if row is None:
            row = UserAIConfig(owner_id=owner_id, free_used=0)
            db.add(row)
        row.free_used = (row.free_used or 0) + 1
        db.commit()
        logger.info("free AI credit spent by %s (now %s)", owner_id, row.free_used)
    except Exception:  # never fail a completed action over accounting
        logger.exception("failed to record free AI use for %s", owner_id)
        db.rollback()
    finally:
        db.close()


def usage_snapshot(owner_id: str | None) -> dict:
    """Free-tier status for the UI (safe to expose — no key material)."""
    s = get_settings()
    row = _row(owner_id)
    used = (row.free_used if row else 0) or 0
    limit = s.free_ai_limit
    return {
        "free_enabled": _free_configured(s),
        "free_limit": limit,
        "free_used": used,
        "free_remaining": max(0, limit - used),
        "has_own_key": _has_own(row),
    }
