"""Per-user runtime settings — configure each user's own AI provider.

The API key is write-only: it is accepted on PUT/test but never returned (only a
``has_key`` boolean and the list of endpoints that have one). Settings are scoped
to the signed-in user and stored server-side (``user_ai_configs`` table). The
response also reports the user's free-tier usage so the UI can show how many free
AI actions remain.

Keys are held one per endpoint (see :mod:`docforge.ai_keys`), so changing model —
or changing provider and changing back — never costs the user a key they already
saved.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...ai.client import LLMClient, LLMError
from ...ai_keys import key_for, key_shape_error, stored_keys, with_key
from ...ai_quota import plan_ai_for_owner, usage_snapshot
from ...db.models import AnalysisJob, ComplianceRun, GenerationRequest, UserAIConfig
from ...settings_store import (
    ANTHROPIC_DEFAULT_BASE,
    GEMINI_DEFAULT_BASE,
    GEMINI_REASONING_MODEL,
    GEMINI_WORKHORSE_MODEL,
    OPENAI_DEFAULT_BASE,
    AIConfig,
    default_base_url,
)
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_settings_dep

router = APIRouter(tags=["settings"])


class AISettingsIn(BaseModel):
    provider: str | None = None  # "openai" | "anthropic"
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    reasoning_model: str | None = None  # optional stronger model for agent loops
    api_key: str | None = None  # write-only; blank = keep existing
    no_think: bool | None = None  # prepend /no_think for Qwen3


def _ai_dto(row: UserAIConfig | None) -> dict:
    """Public view of a user's AI config (never includes the key itself).

    A brand-new user (no row yet) is shown the recommended cloud default —
    Gemini, tiered: a cheap workhorse model plus a stronger reasoning model used
    only for the harder agentic steps. They still need to add their own key.
    """
    if row is None:
        return {
            "provider": "openai",
            "enabled": False,
            "base_url": GEMINI_DEFAULT_BASE,
            "model": GEMINI_WORKHORSE_MODEL,
            "reasoning_model": GEMINI_REASONING_MODEL,
            "has_key": False,
            "saved_endpoints": [],
            "no_think": False,
            "active": False,
            "source": "none",
        }
    # "active" must mean exactly what the pipeline means by it, or the page can
    # report a working key while every action quietly runs the offline engine.
    plan = plan_ai_for_owner(row.owner_id)
    base_url = row.base_url or default_base_url(row.provider)
    return {
        "provider": row.provider or "openai",
        "enabled": bool(row.enabled),
        "base_url": base_url,
        "model": row.model or "gpt-4o-mini",
        "reasoning_model": (row.reasoning_model or "").strip(),
        # Asked of the endpoint this row talks to, so it agrees with
        # usage.has_own_key and with what the pipeline will actually send.
        "has_key": bool(key_for(row.api_key, base_url)),
        # The other endpoints this user has already saved a key for, so the page
        # can say "switching there will reuse the key you saved" instead of
        # implying the key is gone.
        "saved_endpoints": sorted(stored_keys(row.api_key, base_url)),
        "no_think": bool(row.no_think),
        "active": plan.config.active,
        # Which key is actually serving this user right now. Without it the page
        # cannot tell "your key" from "the free tier" and the banners contradict
        # the form.
        "source": plan.mode,
    }


def _token_totals(db: Session, owner_id: str) -> dict:
    """Lifetime AI token usage + estimated cost for a user, across all actions."""
    totals = {"in": 0, "out": 0, "calls": 0, "actions": 0, "cost_usd": 0.0}
    any_cost = False
    for model_cls in (AnalysisJob, GenerationRequest, ComplianceRun):
        try:
            rows = (
                db.query(model_cls.token_usage)
                .filter(model_cls.owner_id == owner_id, model_cls.token_usage.isnot(None))
                .all()
            )
        except Exception:  # pragma: no cover - table may not exist yet
            continue
        for (tu,) in rows:
            if not tu:
                continue
            totals["in"] += int(tu.get("in", 0) or 0)
            totals["out"] += int(tu.get("out", 0) or 0)
            totals["calls"] += int(tu.get("calls", 0) or 0)
            totals["actions"] += 1
            c = tu.get("cost_usd")
            if c is not None:
                any_cost = True
                totals["cost_usd"] += float(c)
    totals["cost_usd"] = round(totals["cost_usd"], 6) if any_cost else None
    return totals


@router.get("/settings")
def get_settings_api(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = db.get(UserAIConfig, user.id)
    return {"ai": _ai_dto(row), "usage": usage_snapshot(user.id), "tokens": _token_totals(db, user.id)}


@router.delete("/settings/account")
def delete_account_api(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Permanently delete the signed-in user's account and ALL their data/files."""
    from ...services.account import delete_account

    summary = delete_account(db, user.id)
    return {"deleted": True, "summary": summary}


@router.get("/logs")
def get_logs_api(
    limit: int = 300,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Recent server-side log entries for the signed-in user (their actions + AI
    calls + errors). Powers the in-app Logs page; ephemeral, process-local."""
    from ...logging_setup import recent_logs

    return {"entries": recent_logs(user.id, limit=max(1, min(limit, 1000)))}


@router.put("/settings")
def put_settings_api(
    body: AISettingsIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = db.get(UserAIConfig, user.id)
    if row is None:
        row = UserAIConfig(owner_id=user.id)
        db.add(row)
    # The endpoint the row talked to BEFORE this save: a bare pre-keyring value
    # belongs to that one, even when this same request repoints the row.
    previous_base = row.base_url or default_base_url(row.provider)
    patch = body.model_dump(exclude_none=True)
    for key in ("provider", "enabled", "base_url", "model", "reasoning_model", "no_think"):
        if key in patch:
            setattr(row, key, patch[key])
    # Store where to reach the provider. Without it the config is inert, so
    # saving a key would appear to work and change nothing.
    if not (row.base_url or "").strip():
        row.base_url = default_base_url(row.provider)
    # A blank api_key never clobbers a stored key, and neither does a value that
    # cannot be a key for this endpoint. The field is masked, so a password
    # manager filling it with an unrelated saved credential is invisible until
    # the next AI action fails -- which is exactly how this key went missing.
    if patch.get("api_key"):
        submitted = patch["api_key"].strip()
        problem = key_shape_error(row.base_url, submitted)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        row.api_key = with_key(
            row.api_key, row.base_url, submitted, legacy_base=previous_base
        )
    db.commit()
    db.refresh(row)
    return {"ai": _ai_dto(row), "usage": usage_snapshot(user.id), "tokens": _token_totals(db, user.id)}


@router.post("/settings/ai/test")
def test_ai(
    body: AISettingsIn,
    db: Session = Depends(get_db),
    settings=Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Try a tiny completion with the proposed (or stored) per-user config."""
    row = db.get(UserAIConfig, user.id)
    provider = body.provider or (row.provider if row else None) or "openai"
    default_base = ANTHROPIC_DEFAULT_BASE if provider == "anthropic" else OPENAI_DEFAULT_BASE
    base_url = body.base_url or (row.base_url if row else None) or default_base
    # Test the key that belongs to the endpoint being tested — the stored one
    # for a different provider would only ever produce a confusing 401.
    stored = key_for(row.api_key, base_url) if row else ""
    cfg = AIConfig(
        provider=provider,
        enabled=True,
        base_url=base_url,
        api_key=body.api_key or stored or "",
        model=body.model or (row.model if row else None) or "",
        timeout_seconds=settings.ai_interactive_timeout_seconds,
        max_retries=0,
    )
    if not cfg.api_key:
        return {"ok": False, "message": "No API key configured."}
    try:
        text = LLMClient(cfg).complete(
            [{"role": "user", "content": "Reply with the single word OK."}], json_mode=False
        )
        reply = (text or "").strip()[:60] or "(empty)"
        return {"ok": True, "message": f"Connected to {cfg.provider}/{cfg.model}. Reply: {reply}"}
    except LLMError as exc:
        return {"ok": False, "message": str(exc)}
