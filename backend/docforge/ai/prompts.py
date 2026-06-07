"""Prompt templates + strict response schemas for the three AI tasks (spec §10).

Each builder returns (system, developer, user) strings. Responses are validated
against the Pydantic models here before being mapped onto the domain schema.
"""

from __future__ import annotations

import json
import typing
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..schemas.diff import DiffRunResult
from ..schemas.enums import ElementType
from ..schemas.extraction import DocumentExtraction
from ..schemas.template import FieldDefinition

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class _LenientLLMModel(BaseModel):
    """Base for LLM response models that tolerates the small JSON imperfections
    local models routinely produce.

    Qwen3 and other local models frequently emit ``null`` for fields the schema
    declares as lists (``"enum_values": null``) or required strings. Strict
    Pydantic rejects these, which previously caused every *valid* classification
    to fail validation and burn three slow repair retries before falling back to
    heuristics. We coerce ``null`` → ``[]`` for list fields and ``null`` → ``""``
    for plain (non-optional) string fields, so good output is accepted as-is.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for name, field in cls.model_fields.items():
            if name not in data or data[name] is not None:
                continue
            ann = field.annotation
            origin = typing.get_origin(ann)
            if origin in (list, tuple, set):
                data[name] = []
            elif ann is str and not field.is_required():
                # Coerce null -> "" ONLY for optional/defaulted strings (e.g.
                # description, rationale, title). A null in a *required*
                # identifier (node_id, section_key, field_name) is a strong
                # signal of a garbled response — leave it None so validation
                # fails and the repair/retry loop kicks in instead of silently
                # dropping the element downstream.
                data[name] = ""
        return data


class LLMElementClassification(_LenientLLMModel):
    node_id: str
    classification: str = "UNKNOWN"
    field_name: str | None = None
    field_type: str | None = None
    description: str = ""
    required: bool = True
    confidence: float = 0.5
    validation_hints: list[str] = Field(default_factory=list)
    static_prefix: str | None = None
    static_suffix: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    rationale: str = ""


class LLMSection(_LenientLLMModel):
    section_key: str
    title: str = ""
    purpose: str = ""
    expected_content: str = ""
    field_names: list[str] = Field(default_factory=list)
    related_sections: list[str] = Field(default_factory=list)


class LLMClassifyResponse(_LenientLLMModel):
    document_type_guess: str = ""
    classifications: list[LLMElementClassification] = Field(default_factory=list)
    sections: list[LLMSection] = Field(default_factory=list)


class LLMPlacement(_LenientLLMModel):
    field_name: str
    value: Any = None
    confidence: float = 1.0
    source_excerpt: str = ""
    ambiguous: bool = False
    alternatives: list[str] = Field(default_factory=list)
    note: str = ""


class LLMRouteResponse(_LenientLLMModel):
    placements: list[LLMPlacement] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    unmapped_content: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Task A + B: classify elements / infer sections
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are DocForge's document-template analyst. Given the elements of a filled "
    "business document (and, when available, cross-document diff evidence), you "
    "classify each element so a reusable template can be generated. You decide what "
    "is FIXED boilerplate, what is a DYNAMIC field, what is a REPEATABLE table or "
    "section, and what is AUTO content (page numbers, table of contents, Word fields)."
)

_CLASSIFY_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "document_type_guess": string,
  "classifications": [
    {
      "node_id": string,                  // must match an input node_id
      "classification": one of
        ["FIXED","DYNAMIC_TEXT","DYNAMIC_DATE","DYNAMIC_PERSON","DYNAMIC_ENUM",
         "DYNAMIC_NUMBER","REPEATABLE_TABLE","REPEATABLE_SECTION","AUTO_FIELD","UNKNOWN"],
      "field_name": snake_case string or null,   // only for DYNAMIC_* / REPEATABLE_*
      "field_type": one of
        ["text","multiline_text","date","person","number","enum","table","boolean"] or null,
      "description": short string,
      "required": boolean,
      "confidence": number 0..1,
      "validation_hints": [string],
      "static_prefix": string or null,    // keep label text static, e.g. "Date: "
      "static_suffix": string or null,
      "enum_values": [string],
      "rationale": short string
    }
  ],
  "sections": [
    {"section_key": string, "title": string, "purpose": string,
     "expected_content": string, "field_names": [string], "related_sections": [string]}
  ]
}

Rules:
- Use the diff evidence as the primary signal: identical across samples => FIXED;
  values that change => DYNAMIC_*; a table whose row count or rows vary but whose
  header is stable => REPEATABLE_TABLE.
- When a dynamic value follows a label (e.g. "Invoice Date: 2026-06-01"), keep the
  label in static_prefix ("Invoice Date: ") and make ONLY the value dynamic.
- Use AUTO_FIELD for page numbers, TOC and Word fields. Never invent field_names
  for FIXED/AUTO content.
- field_name must be snake_case and unique.
- Output valid JSON only. No prose, no markdown.
"""


def _node_payload(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    node_ids: set[str] | None = None,
) -> list[dict]:
    diff_by_node = {d.representative_node_id: d for d in (diff.node_diffs if diff else [])}
    payload: list[dict] = []
    for e in extraction.top_level_elements():
        if node_ids is not None and e.node_id not in node_ids:
            continue
        node: dict[str, Any] = {
            "node_id": e.node_id,
            "type": e.type.value,
            "style": e.style_name,
            "text": (e.text or "")[:200],
            "hints": e.semantic_hints,
        }
        if e.type == ElementType.TABLE and e.table_structure:
            node["table_headers"] = e.table_structure.headers
            node["n_rows"] = e.table_structure.n_rows
        nd = diff_by_node.get(e.node_id)
        if nd:
            node["evidence"] = {
                "status": nd.status.value,
                "samples": [s[:80] for s in nd.sample_texts[:4]],
                "detected_kind": nd.detected_kind,
                "static_prefix": nd.static_prefix,
                "row_count_variable": nd.row_count_variable,
                "confidence": round(nd.confidence, 2),
            }
        payload.append(node)
    return payload


def build_classify_prompt(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    node_ids: set[str] | None = None,
    include_sections: bool = True,
) -> tuple[str, str, str]:
    """Build the (system, developer, user) classify prompt.

    ``node_ids`` scopes the prompt to a subset of elements so large documents can
    be classified in batches (one response per batch never exceeds the model's
    output limit). ``include_sections`` requests the section grouping only once
    (on the first batch) to avoid redundant output on later batches.
    """
    nodes = _node_payload(extraction, diff, node_ids)
    if include_sections:
        tail = "Classify every node_id above and group them into sections."
    else:
        tail = (
            "Classify every node_id above. Return an empty \"sections\" array "
            "([]) — do not produce sections for this batch."
        )
    user = (
        f"Number of sample documents analyzed: {diff.n_documents if diff else 1}.\n"
        f"Document elements (top-level), with diff evidence where available:\n"
        f"{json.dumps(nodes, ensure_ascii=False, indent=2)}\n\n"
        f"{tail}"
    )
    return _CLASSIFY_SYSTEM, _CLASSIFY_DEVELOPER, user


# ---------------------------------------------------------------------------
# Task C: route unstructured / structured content into template fields
# ---------------------------------------------------------------------------

_ROUTE_SYSTEM = (
    "You are DocForge's content router. You take a user's content — either "
    "structured JSON or unstructured notes — and map it onto the fields of a "
    "known document template, producing precise placement instructions."
)

_ROUTE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "placements": [
    {"field_name": string,          // must be one of the template field names
     "value": any,                  // scalar; OR a list of row-objects for table fields
     "confidence": number 0..1,
     "source_excerpt": string,      // the snippet of input this came from
     "ambiguous": boolean,
     "alternatives": [string],
     "note": string}
  ],
  "missing_required": [string],     // required field names with no value found
  "ambiguous_fields": [string],
  "unmapped_content": [string]      // input chunks that did not fit any field
}

Rules:
- Only use field_name values from the provided template fields. Never invent fields.
- For a table field, "value" MUST be a list of objects keyed by the table's column
  field_names.
- Respect field types (dates as date-like strings, numbers as numbers/strings).
- If a required field has no corresponding content, list it in missing_required.
- Set ambiguous=true and populate alternatives when content could fit >1 field.
- Output valid JSON only. No prose, no markdown.
"""


def _fields_payload(fields: list[FieldDefinition]) -> list[dict]:
    out = []
    for f in fields:
        item: dict[str, Any] = {
            "field_name": f.field_name,
            "label": f.label,
            "type": f.field_type.value,
            "required": f.required,
            "description": f.description,
        }
        if f.enum_values:
            item["allowed_values"] = f.enum_values
        if f.columns:
            item["columns"] = [
                {"field_name": c.field_name, "label": c.label, "type": c.field_type.value}
                for c in f.columns
            ]
        out.append(item)
    return out


def build_route_prompt(
    fields: list[FieldDefinition],
    *,
    raw_text: str | None = None,
    structured_data: dict | None = None,
    from_document: bool = False,
) -> tuple[str, str, str]:
    parts = [
        "Template fields:\n"
        + json.dumps(_fields_payload(fields), ensure_ascii=False, indent=2)
    ]
    if structured_data:
        parts.append(
            "Structured input (map/validate against the fields):\n"
            + json.dumps(structured_data, ensure_ascii=False, indent=2)
        )
    if raw_text:
        if from_document:
            parts.append(
                "The text below was extracted from an uploaded document whose layout and "
                "structure may NOT match this template. Ignore the source document's original "
                "format, headings and ordering. Treat it purely as a pool of text and map only "
                "the pieces of meaning that genuinely fit a template field; put anything that "
                "doesn't fit into unmapped_content. Do not force-fit unrelated text into a field, "
                "and do not dump large multi-topic blocks into a single field.\n\n"
                "Extracted document text:\n" + raw_text
            )
        else:
            parts.append("Unstructured input to route:\n" + raw_text)
    parts.append("Produce placement instructions for the fields above.")
    return _ROUTE_SYSTEM, _ROUTE_DEVELOPER, "\n\n".join(parts)
