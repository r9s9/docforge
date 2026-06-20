"""LLM-backed classifier. Produces the same ClassificationResult schema as the
heuristic path, so callers are agnostic to which engine ran.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..ai.client import LLMCancelled, LLMClient, _extract_json
from ..ai.prompts import LLMClassifyResponse, build_classify_prompt
from ..common.textutil import slugify_field
from ..schemas.classification import (
    ClassificationResult,
    ElementClassification,
    SectionUnderstanding,
)
from ..schemas.diff import DiffRunResult
from ..schemas.enums import ClassificationType, FieldType
from ..schemas.extraction import DocumentExtraction


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


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _run_batch(
    client, system, developer, user, on_delta, cancel_event
) -> LLMClassifyResponse:
    """Classify one batch. Stream when possible (live progress), with a robust
    non-streaming + repair fallback if the streamed JSON can't be parsed."""
    if on_delta is not None and client.supports_streaming:
        messages = [
            {"role": "system", "content": system},
            {"role": "system", "content": f"[developer instructions]\n{developer}"},
            {"role": "user", "content": user},
        ]
        raw = client.stream_openai(messages, on_delta=on_delta, cancel_event=cancel_event)
        data = _extract_json(raw)
        if data is not None:
            try:
                return LLMClassifyResponse.model_validate(data)
            except ValidationError:
                pass  # fall through to the repair loop below
    return client.complete_json(
        system=system, developer=developer, user=user,
        schema=LLMClassifyResponse, cancel_event=cancel_event,
    )


def classify_llm(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    client: LLMClient,
    on_progress=None,
    cancel_event=None,
) -> ClassificationResult:
    node_ids = [e.node_id for e in extraction.top_level_elements()]
    batches = _chunk(node_ids, CLASSIFY_BATCH_SIZE) or [[]]
    n_batches = len(batches)

    merged: list = []
    sections: list = []
    document_type_guess = ""

    for bi, batch_ids in enumerate(batches):
        if cancel_event is not None and cancel_event.is_set():
            raise LLMCancelled("cancelled before classify batch")
        first = bi == 0
        system, developer, user = build_classify_prompt(
            extraction, diff, node_ids=set(batch_ids), include_sections=first
        )
        on_delta = None
        if on_progress is not None and client.supports_streaming:
            target = max(150, len(batch_ids) * 45)
            state = {"n": 0}

            def on_delta(_chunk_text, _acc, _bi=bi, _target=target, _state=state):
                _state["n"] += 1
                frac = (_bi + min(0.99, _state["n"] / _target)) / n_batches
                label = (
                    f"AI classifying… batch {_bi + 1}/{n_batches} "
                    f"({_state['n']} tokens)"
                )
                on_progress(label, min(0.99, frac))

        try:
            resp = _run_batch(client, system, developer, user, on_delta, cancel_event)
        except LLMCancelled:
            raise  # cancellation must propagate, never fall back to heuristics
        merged.extend(resp.classifications)
        if first:
            sections = resp.sections
            document_type_guess = resp.document_type_guess
        elif not document_type_guess and resp.document_type_guess:
            document_type_guess = resp.document_type_guess

    combined = LLMClassifyResponse(
        document_type_guess=document_type_guess,
        classifications=merged,
        sections=sections,
    )
    result = map_response(extraction, combined, client.model)
    _apply_optional_from_diff(result, diff)
    if on_progress is not None:
        on_progress("AI classification complete", 1.0)
    return result
