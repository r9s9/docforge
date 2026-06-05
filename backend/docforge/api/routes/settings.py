"""Runtime settings endpoints — configure the AI provider from the UI.

The API key is write-only: it is accepted on PUT/test but never returned (only a
``has_key`` boolean is exposed).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...ai.client import LLMClient, LLMError
from ...settings_store import AIConfig, get_ai_config, update_ai_config

router = APIRouter(tags=["settings"])


class AISettingsIn(BaseModel):
    provider: str | None = None  # "openai" | "anthropic"
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None  # write-only; blank = keep existing
    no_think: bool | None = None  # prepend /no_think for Qwen3


def _ai_dto(cfg: AIConfig) -> dict:
    return {
        "provider": cfg.provider,
        "enabled": cfg.enabled,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_key": bool(cfg.api_key),
        "no_think": cfg.no_think,
        "active": cfg.active,
    }


@router.get("/settings")
def get_settings_api() -> dict:
    return {"ai": _ai_dto(get_ai_config())}


@router.put("/settings")
def put_settings_api(body: AISettingsIn) -> dict:
    cfg = update_ai_config(body.model_dump(exclude_none=True))
    return {"ai": _ai_dto(cfg)}


@router.post("/settings/ai/test")
def test_ai(body: AISettingsIn) -> dict:
    """Try a tiny completion with the proposed (or stored) config."""
    base = get_ai_config()
    cfg = AIConfig(
        provider=body.provider or base.provider,
        enabled=True,
        base_url=body.base_url or base.base_url,
        api_key=body.api_key or base.api_key,
        model=body.model or base.model,
        timeout_seconds=base.timeout_seconds,
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
