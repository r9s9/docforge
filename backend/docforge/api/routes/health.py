"""Health / capability endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import __version__
from ...services.pdf import pdf_available
from ...settings_store import get_ai_config
from ..auth import CurrentUser, get_current_user

router = APIRouter(tags=["system"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Identify the signed-in user (used by the frontend to confirm the session)."""
    return {"id": user.id, "email": user.email}


@router.get("/health")
def health() -> dict:
    ai = get_ai_config()
    return {
        "status": "ok",
        "version": __version__,
        "ai_active": ai.active,
        "ai_provider": ai.provider if ai.active else None,
        "ai_model": ai.model if ai.active else None,
        "pdf_export": pdf_available(),
        "generation_modes": ["structured_json", "structured_form", "unstructured_text"],
    }
