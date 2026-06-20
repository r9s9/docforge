"""Per-user runtime settings — configure each user's own AI provider.

The API key is write-only: it is accepted on PUT/test but never returned (only a
``has_key`` boolean is exposed). Settings are scoped to the signed-in user and
stored server-side (``user_ai_configs`` table). The response also reports the
user's free-tier usage so the UI can show how many free AI actions remain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...ai.client import LLMClient, LLMError
from ...ai_quota import usage_snapshot
from ...db.models import UserAIConfig
from ...settings_store import (
    ANTHROPIC_DEFAULT_BASE,
    OPENAI_DEFAULT_BASE,
    AIConfig,
)
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_settings_dep

router = APIRouter(tags=["settings"])


class AISettingsIn(BaseModel):
    provider: str | None = None  # "openai" | "anthropic"
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # write-only; blank = keep existing
    no_think: bool | None = None  # prepend /no_think for Qwen3


def _ai_dto(row: UserAIConfig | None) -> dict:
    """Public view of a user's AI config (never includes the key itself)."""
    if row is None:
        return {
            "provider": "openai",
            "enabled": False,
            "base_url": OPENAI_DEFAULT_BASE,
            "model": "gpt-4o-mini",
            "has_key": False,
            "no_think": False,
            "active": False,
        }
    return {
        "provider": row.provider or "openai",
        "enabled": bool(row.enabled),
        "base_url": row.base_url or OPENAI_DEFAULT_BASE,
        "model": row.model or "gpt-4o-mini",
        "has_key": bool((row.api_key or "").strip()),
        "no_think": bool(row.no_think),
        "active": bool(row.enabled and (row.api_key or "").strip()),
    }


@router.get("/settings")
def get_settings_api(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    row = db.get(UserAIConfig, user.id)
    return {"ai": _ai_dto(row), "usage": usage_snapshot(user.id)}


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
    patch = body.model_dump(exclude_none=True)
    for key in ("provider", "enabled", "base_url", "model", "no_think"):
        if key in patch:
            setattr(row, key, patch[key])
    # A blank api_key never clobbers an existing stored key.
    if patch.get("api_key"):
        row.api_key = patch["api_key"].strip()
    db.commit()
    db.refresh(row)
    return {"ai": _ai_dto(row), "usage": usage_snapshot(user.id)}


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
    cfg = AIConfig(
        provider=provider,
        enabled=True,
        base_url=body.base_url or (row.base_url if row else None) or default_base,
        api_key=body.api_key or (row.api_key if row else None) or "",
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
