"""Generation compose step: refine routed values and draft missing required ones.

Routing answers *where* content goes; composition makes the values
document-ready — formatted to each field's type/description, expanded into prose
for multiline fields, and drafted from context for required fields that routing
left empty (flagged ``ai_drafted`` for review). Runs on the reasoning tier with
deterministic helper tools (date/number normalisers + a value validator), and is
strictly best-effort: any failure returns the original routing unchanged.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..ai.prompts import LLMComposeResponse, build_compose_prompt
from ..ai.tools import compose_tools, validate_field_value
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition
from ..settings_store import REASONING_TIER

logger = logging.getLogger("docforge.ai_router")


def _clamp(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.6


def compose_values(
    routing: RoutingResult,
    fields: list[FieldDefinition],
    *,
    source_text: str = "",
    structured_data: dict | None = None,
    client: LLMClient,
    cancel_event=None,
) -> RoutingResult:
    """Refine ``routing``'s values via the compose agent; return an updated result.

    No-op (returns ``routing``) when AI is inactive or the compose call fails.
    """
    if not client.active or not fields:
        return routing

    system, developer, user = build_compose_prompt(
        fields, routing.placements,
        source_text=source_text, structured_data=structured_data,
        missing_required=routing.missing_required,
    )
    try:
        resp = client.complete_agentic(
            system=system, developer=developer, user=user, schema=LLMComposeResponse,
            tools=compose_tools(fields), tier=REASONING_TIER, cancel_event=cancel_event,
        )
    except LLMError:
        logger.debug("compose step failed; keeping routed values", exc_info=True)
        return routing

    valid = {f.field_name for f in fields}
    existing: dict[str, PlacementInstruction] = {p.field_name: p for p in routing.placements}
    for cv in resp.values:
        if cv.field_name not in valid or cv.value in (None, ""):
            continue
        p = existing.get(cv.field_name)
        if p is None:
            existing[cv.field_name] = PlacementInstruction(
                field_name=cv.field_name, value=cv.value, confidence=_clamp(cv.confidence),
                ai_drafted=cv.ai_drafted, note=cv.note or ("AI-drafted" if cv.ai_drafted else ""),
            )
        else:
            p.value = cv.value
            p.confidence = _clamp(cv.confidence)
            if cv.ai_drafted:
                p.ai_drafted = True
                p.note = cv.note or "AI-drafted"
            elif cv.note:
                p.note = cv.note

    placements = list(existing.values())

    # Deterministic cross-check: the model's confidence/ambiguous fields are
    # self-rated with nothing independently verifying them. Re-run the same
    # type/enum check the compose tool loop had access to against every FINAL
    # value and downgrade confidence when it fails — so a wrong date/number/enum
    # value is flagged for review even if the model was confidently wrong.
    by_name = {f.field_name: f for f in fields}
    n_flagged = 0
    for p in placements:
        f = by_name.get(p.field_name)
        if f is None or p.value in (None, ""):
            continue
        check = validate_field_value(f, p.value)
        if not check.get("ok", True):
            n_flagged += 1
            p.confidence = min(p.confidence, 0.3)
            flag = f"Needs review — {check.get('reason') or 'failed validation'}."
            p.note = f"{p.note} {flag}".strip() if p.note else flag

    placed = {p.field_name for p in placements if p.value not in (None, "")}
    missing = [f.field_name for f in fields if f.required and f.field_name not in placed]
    n_drafted = sum(1 for p in placements if p.ai_drafted)
    logger.info(
        "compose refined %d value(s), drafted %d, flagged %d on validation, %d required still missing",
        len(placements), n_drafted, n_flagged, len(missing),
    )
    return routing.model_copy(update={"placements": placements, "missing_required": missing})
