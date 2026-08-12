"""Change a draft by asking for it, in words.

Everything else in generation is one-shot: supply content, get a document, then
edit fields by hand. But the useful last mile of writing is conversational —
"shorten the summary", "move the vendor risk into scope", "make the tone more
formal" — and expressing that as a form edit means doing the work yourself.

A refine turn is deliberately stateless: the conversation and the current values
travel with the request, so there is no session to expire, no draft to
reconcile, and a turn can be retried or abandoned freely. What comes back is a
*patch* — only the fields that changed — which the review screen applies over
its own state, keeping the user in control of what lands.

Rendering stays deterministic: refine only ever changes values, never the
document's design.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from sqlalchemy.orm import Session

from ..ai.client import LLMClient, LLMError
from ..ai.prompts import LLMRefineResponse, build_refine_prompt
from ..ai.tools import validate_field_value
from ..ai_router.context import build_template_context
from ..config import Settings, get_settings
from ..db.models import Template
from ..schemas.extraction import DocumentExtraction
from ..settings_store import REASONING_TIER, generation_ai_config
from ..template_registry import TemplateRegistry

logger = logging.getLogger("docforge.refine")


class RefineUnavailable(RuntimeError):
    """Raised when no AI is configured — refine has no offline equivalent."""


def _clamp(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.8


def refine_values(
    db: Session,
    template: Template,
    *,
    version: int | None,
    messages: list,
    current_values: dict,
    source_context: str = "",
    registry: TemplateRegistry | None = None,
    settings: Settings | None = None,
    owner_id: str | None = None,
) -> dict:
    """Apply one conversational edit; returns the reply and the value patch."""
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = version or template.latest_version
    fields = registry.load_fields(template.id, version)

    # A chat turn sits between the two existing budgets: too slow for the
    # interactive cap, far too long to make someone wait a generation timeout.
    config = replace(
        generation_ai_config(), timeout_seconds=settings.ai_refine_timeout_seconds
    )
    client = LLMClient(config).for_tier(REASONING_TIER)
    if not client.active:
        raise RefineUnavailable("Connect an AI provider in Settings to use Refine.")

    system, developer, user = build_refine_prompt(
        fields,
        messages,
        current_values,
        template_context=_template_context(registry, template, version, fields),
        source_context=source_context,
    )
    # Plain completion, not the tool loop: this must work on every provider, and
    # a single focused edit has nothing to look up that the prompt lacks.
    response = client.complete_json(
        system=system, developer=developer, user=user, schema=LLMRefineResponse
    )

    by_name = {f.field_name: f for f in fields}
    updates: list[dict] = []
    for update in response.updates:
        field = by_name.get(update.field_name)
        if field is None or update.value in (None, ""):
            continue
        note = update.note or ("AI-drafted" if update.ai_drafted else "")
        check = validate_field_value(field, update.value)
        confidence = _clamp(update.confidence)
        if not check.get("ok", True):
            confidence = min(confidence, 0.3)
            flag = f"Needs review — {check.get('reason') or 'failed validation'}."
            note = f"{note} {flag}".strip() if note else flag
        updates.append(
            {
                "field_name": update.field_name,
                "value": update.value,
                "confidence": confidence,
                "ai_drafted": update.ai_drafted,
                "note": note,
            }
        )

    removed = [name for name in response.removed if name in by_name]
    logger.info(
        "refine changed %d field(s), cleared %d, skipped %d section(s)",
        len(updates), len(removed), len(response.skip_sections),
    )
    return {
        "reply": response.reply.strip(),
        "updates": updates,
        "removed": removed,
        "skip_sections": response.skip_sections,
        "model_used": client.model,
    }


def _template_context(registry, template: Template, version: int, fields) -> dict:
    """The document's shape, so an edit is made with its place in mind."""
    try:
        intelligence = registry.load_intelligence(template.id, version)
    except Exception:
        return {}
    representative = None
    try:
        raw = registry.load_representative(template.id, version)
        if raw:
            representative = DocumentExtraction.model_validate(raw)
    except Exception:
        logger.debug("no representative for refine context", exc_info=True)
    return build_template_context(
        document_type=intelligence.document_type_guess,
        sections=intelligence.sections,
        classifications=intelligence.classifications,
        fields=fields,
        representative=representative,
    )
