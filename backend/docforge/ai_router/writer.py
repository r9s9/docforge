"""Write the whole document in one pass.

Routing then composing answers two questions separately — *where does each piece
of content go*, then *how should each value read* — and neither step ever sees
the document as a whole. That is why output could be correct field by field and
still read like assembled fragments: the summary repeating the body, two
sections stating the same fact, an empty section padded with filler.

The writer replaces both with a single reasoning-tier pass that is given the
template's shape and all of the content at once, and returns every field
together. Seeing the whole document is what makes cross-field judgement possible
— saying something once, keeping one voice, and deciding a section has nothing
to say rather than inventing something for it.

It is strictly an upgrade path: any failure falls back to route + compose, which
in turn falls back to the offline heuristics, so a writer problem can never cost
more than the quality it was added to provide.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..ai.prompts import LLMWriteResponse, build_writer_prompt
from ..ai.tools import writer_tools
from ..schemas.extraction import DocumentExtraction
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition
from ..settings_store import REASONING_TIER
from .compose import apply_validation_flags

logger = logging.getLogger("docforge.ai_router.writer")

# One call has to emit every field, and output tokens are capped per call. Past
# roughly this many fields a single response would truncate, so the older
# batched route+compose path is the better tool for the job.
MAX_WRITER_FIELDS = 60


def _clamp(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.7


def write_document(
    fields: list[FieldDefinition],
    *,
    client: LLMClient,
    template_id: str,
    version: int,
    template_context: dict | None = None,
    source_outline: str = "",
    source_doc: DocumentExtraction | None = None,
    raw_text: str | None = None,
    structured_data: dict | None = None,
    learned_hints: str = "",
    review_findings: list[dict] | None = None,
    prior_values: dict | None = None,
    cancel_event=None,
) -> RoutingResult:
    """Write every field of the document in one pass. Raises on failure."""
    system, developer, user = build_writer_prompt(
        fields,
        template_context=template_context,
        source_outline=source_outline,
        raw_text=raw_text,
        structured_data=structured_data,
        learned_hints=learned_hints,
        review_findings=review_findings,
        prior_values=prior_values,
    )
    response = client.complete_agentic(
        system=system,
        developer=developer,
        user=user,
        schema=LLMWriteResponse,
        tools=writer_tools(fields, template_context, source_doc),
        tier=REASONING_TIER,
        cancel_event=cancel_event,
    )

    valid = {f.field_name for f in fields}
    placements: list[PlacementInstruction] = []
    seen: set[str] = set()
    for written in response.placements:
        if written.field_name not in valid or written.field_name in seen:
            continue
        if written.value in (None, ""):
            continue
        seen.add(written.field_name)
        placements.append(
            PlacementInstruction(
                field_name=written.field_name,
                value=written.value,
                confidence=_clamp(written.confidence),
                source_excerpt=written.source_excerpt,
                ambiguous=written.ambiguous,
                alternatives=[a for a in written.alternatives if a in valid],
                note=written.note or ("AI-drafted" if written.ai_drafted else ""),
                ai_drafted=written.ai_drafted,
            )
        )

    n_flagged = apply_validation_flags(placements, fields)
    missing = [f.field_name for f in fields if f.required and f.field_name not in seen]
    skipped = [
        {"section_key": s.section_key, "reason": s.reason}
        for s in response.skipped_sections
        if s.section_key
    ]
    logger.info(
        "writer produced %d value(s), drafted %d, flagged %d, skipped %d section(s), "
        "%d required still missing",
        len(placements),
        sum(1 for p in placements if p.ai_drafted),
        n_flagged,
        len(skipped),
        len(missing),
    )
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        ambiguous_fields=[p.field_name for p in placements if p.ambiguous],
        unmapped_content=response.unmapped_content,
        skipped_sections=skipped,
        model_used=client.config.model_for_tier(REASONING_TIER),
        source="writer",
    )


def try_write_document(fields: list[FieldDefinition], **kwargs) -> RoutingResult | None:
    """Attempt the writer, returning ``None`` so the caller can fall back.

    Never raises for a content reason: cancellation still propagates (the user
    asked to stop), but every other failure means "use the older path".
    """
    from ..ai.client import LLMCancelled
    from ..config import get_settings

    if not get_settings().ai_writer_enabled:
        return None
    if len(fields) > MAX_WRITER_FIELDS:
        logger.info(
            "template has %d fields (limit %d) — using batched routing instead of the writer",
            len(fields),
            MAX_WRITER_FIELDS,
        )
        return None
    try:
        return write_document(fields, **kwargs)
    except LLMCancelled:
        raise
    except LLMError as exc:
        logger.warning("writer failed, falling back to route+compose: %s", exc)
    except Exception:
        logger.exception("unexpected writer error; falling back to route+compose")
    return None
