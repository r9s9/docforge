"""Read the assembled document back and report what reads wrong.

Every check before this point looks at values in isolation: the validator asks
whether a date parses, the composer asks whether a value suits its field. None
of them can see the finished document, so the failures that survive are exactly
the ones a person notices immediately — a section that promises content and
delivers none, the same point made twice under different headings, a paragraph
sitting under the wrong one.

This pass renders nothing new: it reads the blocks already parsed out of the
generated DOCX and asks a cheap model what a recipient would notice. It is
strictly advisory and strictly best-effort — any failure returns no findings, so
a review problem can never block a document from being produced.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..ai.prompts import LLMRenderReview, build_render_review_prompt
from ..schemas.routing import RoutingResult
from ..settings_store import WORKHORSE_TIER

logger = logging.getLogger("docforge.ai_router.verify")

# Findings at this severity are worth spending a second writer pass to fix.
_CORRECTABLE = "error"


def review_rendered_output(
    blocks: list[dict],
    routing: RoutingResult,
    *,
    client: LLMClient,
    template_context: dict | None = None,
    cancel_event=None,
) -> list[dict]:
    """Findings about the assembled document; ``[]`` when clean or unavailable."""
    if not client.active or not blocks:
        return []
    system, developer, user = build_render_review_prompt(
        blocks,
        template_context=template_context,
        placed_fields=[p.field_name for p in routing.placements],
        skipped_sections=routing.skipped_sections,
    )
    try:
        response = client.for_tier(WORKHORSE_TIER).complete_json(
            system=system, developer=developer, user=user,
            schema=LLMRenderReview, cancel_event=cancel_event,
        )
    except LLMError:
        logger.debug("render review failed; continuing without findings", exc_info=True)
        return []
    except Exception:
        logger.exception("unexpected render review error; continuing without findings")
        return []

    findings = [
        f.model_dump(mode="json") for f in response.findings if (f.message or "").strip()
    ]
    if findings:
        logger.info(
            "render review found %d issue(s): %s",
            len(findings),
            "; ".join(f"{f['kind']}:{f['severity']}" for f in findings),
        )
    return findings


def has_correctable(findings: list[dict]) -> bool:
    """Whether anything found is serious enough to justify rewriting once."""
    return any(f.get("severity") == _CORRECTABLE for f in findings)
