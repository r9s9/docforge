"""LLM-backed classifier. Produces the same ClassificationResult schema as the
heuristic path, so callers are agnostic to which engine ran.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMCancelled, LLMClient, LLMError
from ..ai.prompts import (
    LLMClassifyResponse,
    LLMCritiqueResponse,
    LLMUnderstanding,
    build_classify_prompt,
    build_critique_prompt,
    build_understanding_prompt,
)
from ..ai.tools import classify_tools
from ..common.textutil import slugify_field
from ..schemas.classification import (
    ClassificationResult,
    ElementClassification,
    SectionUnderstanding,
)
from ..schemas.diff import DiffRunResult
from ..schemas.enums import ClassificationType, FieldType, needs_field
from ..schemas.extraction import DocumentExtraction
from ..settings_store import REASONING_TIER, WORKHORSE_TIER

logger = logging.getLogger("docforge.ai_classifier")


def _coerce_classification(value: str | None) -> ClassificationType:
    try:
        return ClassificationType(value) if value else ClassificationType.UNKNOWN
    except ValueError:
        return ClassificationType.UNKNOWN


def _coerce_field_type(value: str | None) -> FieldType | None:
    if not value:
        return None
    try:
        return FieldType(value)
    except ValueError:
        return None


def _clamp(x: float) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def _unique(name: str, used: set[str]) -> str:
    if name not in used:
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    return f"{name}_{i}"


def map_response(extraction: DocumentExtraction, resp: LLMClassifyResponse, model: str) -> ClassificationResult:
    valid_ids = {e.node_id for e in extraction.elements}
    classifications: list[ElementClassification] = []
    covered: set[str] = set()
    used_names: set[str] = set()

    for c in resp.classifications:
        if c.node_id not in valid_ids or c.node_id in covered:
            continue
        field_name = c.field_name or None
        if field_name:
            # The model may return a label-ish name ("1.1.1 Header 3", "Total (USD)")
            # that isn't a valid Jinja identifier; slugify so the placeholder it
            # becomes ({{ name }}) always compiles.
            field_name = _unique(slugify_field(field_name), used_names)
            used_names.add(field_name)
        classifications.append(
            ElementClassification(
                node_id=c.node_id,
                classification=_coerce_classification(c.classification),
                field_name=field_name,
                field_type=_coerce_field_type(c.field_type),
                description=c.description,
                required=c.required,
                confidence=_clamp(c.confidence),
                validation_hints=c.validation_hints,
                static_prefix=c.static_prefix,
                static_suffix=c.static_suffix,
                enum_values=c.enum_values,
                source="llm",
                rationale=c.rationale,
            )
        )
        covered.add(c.node_id)

    # Default any element the model skipped to FIXED so the template stays intact.
    for e in extraction.elements:
        if e.node_id in covered:
            continue
        classifications.append(
            ElementClassification(
                node_id=e.node_id,
                classification=ClassificationType.FIXED,
                required=False,
                confidence=0.4,
                source="llm",
                rationale="not classified by model; defaulted to fixed",
            )
        )

    sections = [
        SectionUnderstanding(
            section_key=s.section_key,
            title=s.title,
            purpose=s.purpose,
            expected_content=s.expected_content,
            field_names=s.field_names,
            related_sections=s.related_sections,
        )
        for s in resp.sections
    ]

    return ClassificationResult(
        extraction_document_id=extraction.document_id,
        classifications=classifications,
        sections=sections,
        document_type_guess=resp.document_type_guess,
        model_used=model,
        source="llm",
    )


def _apply_optional_from_diff(result: ClassificationResult, diff: DiffRunResult | None) -> None:
    """Optional detection is diff-driven (content absent from some samples), so it
    is applied regardless of which classifier ran — the LLM doesn't decide it."""
    if not diff:
        return
    diff_by_node = {d.representative_node_id: d for d in diff.node_diffs}
    for c in result.classifications:
        nd = diff_by_node.get(c.node_id)
        if nd is not None and nd.is_optional and c.classification != ClassificationType.AUTO_FIELD:
            c.optional = True


# A single classify response holds one object per element. Past ~20 elements the
# JSON output risks exceeding the model's max_output_tokens and getting truncated
# (finish_reason=length), so we classify large documents in batches of this size.
CLASSIFY_BATCH_SIZE = 20
# How many flagged nodes the self-critique pass will re-examine (cost guard).
CRITIQUE_LIMIT = 24


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _summarize_understanding(u: LLMUnderstanding) -> str:
    parts: list[str] = []
    if u.document_type:
        parts.append(f"Type: {u.document_type}")
    if u.summary:
        parts.append(u.summary)
    if u.sections:
        sec = "; ".join(
            f"{s.title or s.section_key}: {s.purpose}".strip(": ")
            for s in u.sections[:8]
            if (s.title or s.section_key)
        )
        if sec:
            parts.append("Sections — " + sec)
    if u.notes:
        parts.append("Notes: " + u.notes)
    return "\n".join(parts)[:2000]


def _run_understanding(
    client: LLMClient, extraction, diff, tools, learned_hints, cancel_event
) -> LLMUnderstanding | None:
    """Pass A — holistic read (reasoning tier). Best-effort: None on failure."""
    system, developer, user = build_understanding_prompt(extraction, diff, learned_hints=learned_hints)
    try:
        return client.complete_agentic(
            system=system, developer=developer, user=user, schema=LLMUnderstanding,
            tools=tools, tier=REASONING_TIER, cancel_event=cancel_event,
        )
    except LLMCancelled:
        raise
    except LLMError:
        logger.debug("understanding pass failed; continuing without it", exc_info=True)
        return None


def _questionable(c: ElementClassification) -> bool:
    """Nodes the critique pass should re-examine."""
    if c.confidence < 0.6:
        return True
    if c.classification == ClassificationType.UNKNOWN:
        return True
    if c.field_name and not (c.description or "").strip():
        return True
    return False


def _draft_view(extraction, diff, flagged: list[ElementClassification]) -> list[dict]:
    by_id = {e.node_id: e for e in extraction.elements}
    diff_by_node = {d.representative_node_id: d for d in (diff.node_diffs if diff else [])}
    out: list[dict] = []
    for c in flagged:
        e = by_id.get(c.node_id)
        item: dict = {
            "node_id": c.node_id,
            "text": (e.text or "")[:300] if e else "",
            "classification": c.classification.value,
            "field_name": c.field_name,
            "field_type": c.field_type.value if c.field_type else None,
            "description": c.description,
            "confidence": round(c.confidence, 2),
        }
        nd = diff_by_node.get(c.node_id)
        if nd:
            item["evidence"] = {
                "status": nd.status.value,
                "samples": [s[:80] for s in nd.sample_texts[:4]],
                "detected_kind": nd.detected_kind,
            }
        out.append(item)
    return out


def _apply_corrections(result: ClassificationResult, resp: LLMCritiqueResponse, extraction) -> int:
    """Merge critique corrections back onto the draft. Returns count applied."""
    valid_ids = {e.node_id for e in extraction.elements}
    by_node = {c.node_id: c for c in result.classifications}
    used_names = {c.field_name for c in result.classifications if c.field_name}
    applied = 0
    for cor in resp.corrections:
        if cor.node_id not in valid_ids or cor.node_id not in by_node:
            continue
        c = by_node[cor.node_id]
        if c.field_name:
            used_names.discard(c.field_name)  # free the old name before reassigning
        cls = _coerce_classification(cor.classification)
        c.classification = cls
        if needs_field(cls):
            name = _unique(slugify_field(cor.field_name or c.field_name or "field"), used_names)
            used_names.add(name)
            c.field_name = name
            c.field_type = _coerce_field_type(cor.field_type) or c.field_type
        else:
            c.field_name = None
            c.field_type = None
        if cor.description:
            c.description = cor.description
        c.required = cor.required
        c.confidence = _clamp(cor.confidence)
        c.static_prefix = cor.static_prefix
        c.static_suffix = cor.static_suffix
        if cor.enum_values:
            c.enum_values = cor.enum_values
        c.rationale = (cor.rationale or c.rationale or "") + " [critique]"
        c.source = "llm"
        applied += 1
    return applied


def _self_critique(
    client, extraction, diff, result, tools, understanding_summary, learned_hints, on_progress, cancel_event
) -> None:
    """Pass C — re-examine the questionable nodes and apply corrections."""
    flagged = [c for c in result.classifications if _questionable(c)][:CRITIQUE_LIMIT]
    if not flagged:
        return
    if on_progress is not None:
        on_progress("AI reviewing its classification…", 0.96)
    system, developer, user = build_critique_prompt(
        _draft_view(extraction, diff, flagged),
        understanding_summary=understanding_summary, learned_hints=learned_hints,
    )
    try:
        resp = client.complete_agentic(
            system=system, developer=developer, user=user, schema=LLMCritiqueResponse,
            tools=tools, tier=REASONING_TIER, cancel_event=cancel_event,
        )
    except LLMCancelled:
        raise
    except LLMError:
        logger.debug("critique pass failed; keeping draft", exc_info=True)
        return
    n = _apply_corrections(result, resp, extraction)
    logger.info("self-critique adjusted %d/%d flagged classification(s)", n, len(flagged))


def classify_llm(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    client: LLMClient,
    on_progress=None,
    cancel_event=None,
    *,
    learned_hints: str = "",
) -> ClassificationResult:
    """Agentic classification: understand (A) -> classify with tools (B) -> critique (C).

    Each element can be classified from its *full* text and cross-document
    evidence (via tools) rather than a truncated snippet. Every stage degrades
    gracefully — understanding/critique are best-effort, and complete_agentic
    itself falls back to single-shot JSON when the endpoint lacks tool support.
    """
    tools = classify_tools(extraction, diff)

    # Pass A — holistic understanding (informs classification).
    understanding = _run_understanding(client, extraction, diff, tools, learned_hints, cancel_event)
    understanding_summary = _summarize_understanding(understanding) if understanding else ""

    # Pass B — classify in batches via the agentic tool loop (workhorse tier).
    node_ids = [e.node_id for e in extraction.top_level_elements()]
    batches = _chunk(node_ids, CLASSIFY_BATCH_SIZE) or [[]]
    n_batches = len(batches)
    merged: list = []
    sections: list = list(understanding.sections) if understanding else []
    document_type_guess = understanding.document_type if understanding else ""

    for bi, batch_ids in enumerate(batches):
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled before classify batch")
        first = bi == 0
        if on_progress is not None:
            on_progress(f"AI classifying… batch {bi + 1}/{n_batches}", 0.35 + 0.55 * bi / n_batches)
        system, developer, user = build_classify_prompt(
            extraction, diff, node_ids=set(batch_ids),
            include_sections=first and understanding is None,
            understanding_summary=understanding_summary, learned_hints=learned_hints,
        )
        resp = client.complete_agentic(
            system=system, developer=developer, user=user, schema=LLMClassifyResponse,
            tools=tools, tier=WORKHORSE_TIER, cancel_event=cancel_event,
        )
        merged.extend(resp.classifications)
        if first and not sections and resp.sections:
            sections = resp.sections
        if not document_type_guess and resp.document_type_guess:
            document_type_guess = resp.document_type_guess

    combined = LLMClassifyResponse(
        document_type_guess=document_type_guess, classifications=merged, sections=sections
    )
    result = map_response(extraction, combined, client.model)

    # Pass C — self-critique of the questionable nodes.
    _self_critique(
        client, extraction, diff, result, tools,
        understanding_summary, learned_hints, on_progress, cancel_event,
    )

    _apply_optional_from_diff(result, diff)
    if on_progress is not None:
        on_progress("AI classification complete", 1.0)
    return result
