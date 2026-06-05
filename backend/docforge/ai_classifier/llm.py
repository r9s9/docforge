"""LLM-backed classifier. Produces the same ClassificationResult schema as the
heuristic path, so callers are agnostic to which engine ran.
"""

from __future__ import annotations

from pydantic import ValidationError

from ..ai.client import LLMClient, LLMError, _extract_json
from ..ai.prompts import LLMClassifyResponse, build_classify_prompt
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
            field_name = _unique(field_name, used_names)
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


def _classify_streaming(extraction, diff, client, system, developer, user, on_progress):
    """Stream the classification so the UI sees live token progress."""
    n_nodes = max(1, len(extraction.top_level_elements()))
    target = max(300, n_nodes * 45)  # rough expected output-token count
    messages = [
        {"role": "system", "content": system},
        {"role": "system", "content": f"[developer instructions]\n{developer}"},
        {"role": "user", "content": user},
    ]
    state = {"n": 0}

    def on_delta(_chunk, _acc):
        state["n"] += 1
        on_progress(f"AI generating classification… {state['n']} tokens", min(0.97, state["n"] / target))

    raw = client.stream_openai(messages, on_delta=on_delta)
    data = _extract_json(raw)
    if data is None:
        raise LLMError("streamed response was not valid JSON")
    try:
        resp = LLMClassifyResponse.model_validate(data)
    except ValidationError as exc:
        raise LLMError(f"streamed response failed schema: {exc.errors()[:2]}") from exc
    result = map_response(extraction, resp, client.model)
    _apply_optional_from_diff(result, diff)
    on_progress("AI classification complete", 1.0)
    return result


def classify_llm(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    client: LLMClient,
    on_progress=None,
) -> ClassificationResult:
    system, developer, user = build_classify_prompt(extraction, diff)

    # Live token streaming when a progress callback is wired and supported.
    if on_progress is not None and client.supports_streaming:
        try:
            return _classify_streaming(extraction, diff, client, system, developer, user, on_progress)
        except LLMError:
            pass  # fall through to the standard (non-streaming) path

    resp = client.complete_json(
        system=system, developer=developer, user=user, schema=LLMClassifyResponse
    )
    result = map_response(extraction, resp, client.model)
    _apply_optional_from_diff(result, diff)
    return result
