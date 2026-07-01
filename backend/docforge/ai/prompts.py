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


class LLMUnderstanding(_LenientLLMModel):
    """Holistic, document-level read produced by the reasoning tier (pass A).

    It precedes per-element classification and *informs* it — what kind of
    document this is, its sections, and which elements are most likely variable.
    """

    document_type: str = ""
    summary: str = ""
    sections: list[LLMSection] = Field(default_factory=list)
    likely_dynamic: list[str] = Field(default_factory=list)  # node_ids likely to vary
    notes: str = ""


class LLMCritiqueResponse(_LenientLLMModel):
    """Self-critique output (pass C): corrected classifications for flagged nodes."""

    corrections: list[LLMElementClassification] = Field(default_factory=list)
    notes: str = ""


class LLMComposedValue(_LenientLLMModel):
    field_name: str
    value: Any = None
    confidence: float = 0.8
    ai_drafted: bool = False  # value was drafted from context, not found verbatim
    note: str = ""


class LLMComposeResponse(_LenientLLMModel):
    """Output of the generation compose step: refined/drafted field values."""

    values: list[LLMComposedValue] = Field(default_factory=list)
    still_missing: list[str] = Field(default_factory=list)


class LLMComplianceVerdict(_LenientLLMModel):
    index: int
    material: bool = True  # a real compliance violation vs a benign/cosmetic diff
    severity: str = "warning"  # error | warning | info
    rationale: str = ""


class LLMComplianceJudgement(_LenientLLMModel):
    """The semantic judge's verdicts over a compliance check's differences."""

    verdicts: list[LLMComplianceVerdict] = Field(default_factory=list)
    summary: str = ""


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
    *,
    understanding_summary: str = "",
    learned_hints: str = "",
) -> tuple[str, str, str]:
    """Build the (system, developer, user) classify prompt.

    ``node_ids`` scopes the prompt to a subset of elements so large documents can
    be classified in batches (one response per batch never exceeds the model's
    output limit). ``include_sections`` requests the section grouping only once
    (on the first batch) to avoid redundant output on later batches.
    ``understanding_summary`` (pass A) and ``learned_hints`` (the user's prior
    corrections) are prepended as context when present.
    """
    nodes = _node_payload(extraction, diff, node_ids)
    if include_sections:
        tail = "Classify every node_id above and group them into sections."
    else:
        tail = (
            "Classify every node_id above. Return an empty \"sections\" array "
            "([]) — do not produce sections for this batch."
        )
    preface_parts: list[str] = []
    if understanding_summary:
        preface_parts.append("Document understanding (context for your decisions):\n" + understanding_summary)
    if learned_hints:
        preface_parts.append(learned_hints)
    preface = ("\n\n".join(preface_parts) + "\n\n") if preface_parts else ""
    user = (
        preface
        + f"Number of sample documents analyzed: {diff.n_documents if diff else 1}.\n"
        + "Element text may be truncated. If a decision is unclear, call "
        + "get_node_text / get_neighbors / get_diff_evidence to read the full "
        + "content before classifying.\n"
        + "Document elements (top-level), with diff evidence where available:\n"
        + f"{json.dumps(nodes, ensure_ascii=False, indent=2)}\n\n"
        + f"{tail}"
    )
    return _CLASSIFY_SYSTEM, _CLASSIFY_DEVELOPER, user


# --- Pass A: holistic document understanding -------------------------------

_UNDERSTAND_SYSTEM = (
    "You are DocForge's senior document analyst. Before any element-by-element "
    "work, you read a whole business document to understand what it is, how it is "
    "organised, and which parts a person fills in per document versus the fixed "
    "boilerplate. Your read guides the detailed classification that follows."
)

_UNDERSTAND_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "document_type": string,            // e.g. "commercial invoice", "NDA", "inspection report"
  "summary": string,                  // 2-4 sentences: purpose + overall structure
  "sections": [
    {"section_key": string, "title": string, "purpose": string,
     "expected_content": string, "field_names": [string], "related_sections": [string]}
  ],
  "likely_dynamic": [string],         // node_ids that most likely vary per document
  "notes": string                     // anything the classifier should watch out for
}
Output valid JSON only. No prose, no markdown.
"""


def build_understanding_prompt(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None,
    *,
    learned_hints: str = "",
) -> tuple[str, str, str]:
    """Pass A: a holistic read of the document (reasoning tier)."""
    nodes = _node_payload(extraction, diff, None)
    preface = (learned_hints + "\n\n") if learned_hints else ""
    user = (
        preface
        + f"Number of sample documents analyzed: {diff.n_documents if diff else 1}.\n"
        + "Full element text is available via get_node_text if a snippet is truncated.\n"
        + "Document elements (top-level), with diff evidence where available:\n"
        + f"{json.dumps(nodes, ensure_ascii=False, indent=2)}\n\n"
        + "Read the whole document and produce the understanding object."
    )
    return _UNDERSTAND_SYSTEM, _UNDERSTAND_DEVELOPER, user


# --- Pass C: self-critique of the draft classification ----------------------

_CRITIQUE_SYSTEM = (
    "You are DocForge's classification reviewer. You receive a draft template "
    "classification and re-examine the questionable parts, correcting mistakes: "
    "FIXED text that should be a DYNAMIC field (or vice versa), wrong field types, "
    "missing labels/static_prefix, vague descriptions, and duplicate field names."
)

_CRITIQUE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "corrections": [
    {  // one entry per node you are CHANGING — same shape as a classification
      "node_id": string,
      "classification": one of
        ["FIXED","DYNAMIC_TEXT","DYNAMIC_DATE","DYNAMIC_PERSON","DYNAMIC_ENUM",
         "DYNAMIC_NUMBER","REPEATABLE_TABLE","REPEATABLE_SECTION","AUTO_FIELD","UNKNOWN"],
      "field_name": snake_case string or null,
      "field_type": one of
        ["text","multiline_text","date","person","number","enum","table","boolean"] or null,
      "description": short, specific string,
      "required": boolean,
      "confidence": number 0..1,
      "static_prefix": string or null,
      "static_suffix": string or null,
      "enum_values": [string],
      "rationale": short string explaining the correction
    }
  ],
  "notes": string
}
Only include nodes you are actually changing. Every DYNAMIC/REPEATABLE field must
have a clear, specific description. Use the tools to read full text when unsure.
Output valid JSON only. No prose, no markdown.
"""


def build_critique_prompt(
    draft: list[dict],
    *,
    understanding_summary: str = "",
    learned_hints: str = "",
) -> tuple[str, str, str]:
    """Pass C: review the draft classification and return only the corrections.

    ``draft`` is a compact list of the current per-node decisions (node_id, text,
    classification, field_name, field_type, description, confidence, evidence).
    """
    preface_parts: list[str] = []
    if understanding_summary:
        preface_parts.append("Document understanding:\n" + understanding_summary)
    if learned_hints:
        preface_parts.append(learned_hints)
    preface = ("\n\n".join(preface_parts) + "\n\n") if preface_parts else ""
    user = (
        preface
        + "Draft classification to review (correct only what is wrong):\n"
        + f"{json.dumps(draft, ensure_ascii=False, indent=2)}\n\n"
        + "Return corrections for the nodes that need fixing."
    )
    return _CRITIQUE_SYSTEM, _CRITIQUE_DEVELOPER, user


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


# ---------------------------------------------------------------------------
# Generation compose: refine/format routed values, draft missing required ones
# ---------------------------------------------------------------------------

_COMPOSE_SYSTEM = (
    "You are DocForge's document author. You take values that were routed into a "
    "template's fields and make them document-ready: correctly formatted for each "
    "field's type, written in the right register, and complete. You never invent "
    "facts that the supplied content does not support."
)

_COMPOSE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "values": [
    {"field_name": string,        // a template field_name
     "value": any,                // refined value (list of row-objects for tables)
     "confidence": number 0..1,
     "ai_drafted": boolean,       // true if you drafted it rather than found it verbatim
     "note": string}
  ],
  "still_missing": [string]       // required fields you could not fill from the content
}

Rules:
- Improve each routed value to fit its field's TYPE and DESCRIPTION: format dates
  as ISO (YYYY-MM-DD) unless the description says otherwise, normalize numbers and
  currency, fix obvious casing/typos, and expand terse notes into complete prose
  for multiline_text fields.
- For enum fields, the value MUST be one of the field's allowed_values.
- For a REQUIRED field with no value, DRAFT a sensible value from the supplied
  content and set ai_drafted=true with a lower confidence. If it is genuinely
  unknowable from the content, leave it out and list it in still_missing.
- NEVER fabricate specific facts (names, totals, dates) not supported by the content.
- Use normalize_date / normalize_number / validate_value to check before finalizing.
- Output valid JSON only. No prose, no markdown.
"""


# The routing step (build_route_prompt) sends raw_text/document content in full
# — compose runs on the SAME content right after routing already succeeded with
# it, so truncating here more tightly would silently starve compose of context
# routing already had. This is a generous backstop against pathological inputs
# (e.g. a multi-megabyte document), not the default path: ~200K chars comfortably
# covers even long multi-page contracts while still bounding worst-case cost.
_COMPOSE_SOURCE_TEXT_CAP = 200_000


def build_compose_prompt(
    fields: list[FieldDefinition],
    placements: list,
    *,
    source_text: str = "",
    structured_data: dict | None = None,
    missing_required: list[str] | None = None,
) -> tuple[str, str, str]:
    """Build the (system, developer, user) compose prompt.

    ``placements`` is the routed values to refine (objects with ``field_name`` /
    ``value``). ``source_text`` is the content they came from (notes or an
    extracted document), used to draft missing values and verify facts.
    """
    current = {p.field_name: p.value for p in placements}
    parts = [
        "Template fields:\n" + json.dumps(_fields_payload(fields), ensure_ascii=False, indent=2),
        "Currently routed values (refine these):\n"
        + json.dumps(current, ensure_ascii=False, default=str, indent=2),
    ]
    if missing_required:
        parts.append(
            "Required fields still missing a value (draft from the content if supported):\n"
            + ", ".join(missing_required)
        )
    if structured_data:
        parts.append(
            "Structured input the user provided:\n"
            + json.dumps(structured_data, ensure_ascii=False, default=str, indent=2)
        )
    if source_text:
        parts.append("Source content the values came from:\n" + source_text[:_COMPOSE_SOURCE_TEXT_CAP])
    parts.append("Return the refined values.")
    return _COMPOSE_SYSTEM, _COMPOSE_DEVELOPER, "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Compliance judge: is each difference a MATERIAL violation or benign?
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are DocForge's compliance reviewer. A deterministic check has compared a "
    "document against its template and listed the differences. For each one you "
    "decide whether it is a MATERIAL compliance violation (changed obligations, "
    "missing required content, altered legal/boilerplate meaning) or a benign, "
    "cosmetic difference (whitespace, synonyms, reformatting, an expected variable "
    "value). You explain each verdict briefly."
)

_JUDGE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "verdicts": [
    {"index": number,          // the difference's index from the input
     "material": boolean,      // true = a real compliance problem
     "severity": one of ["error","warning","info"],
     "rationale": short string}
  ],
  "summary": string
}
Guidance:
- A changed value in a legitimately-variable field is usually benign (info).
- Missing or altered required boilerplate / obligations is usually material (error).
- Reordering, whitespace, casing and synonym wording are usually benign.
- Be specific in the rationale; do not just restate the difference.
- Output valid JSON only. No prose, no markdown.
"""


def build_compliance_judge_prompt(
    document_type: str, differences: list[dict]
) -> tuple[str, str, str]:
    """Build the (system, developer, user) prompt for the compliance judge."""
    user = (
        f"Document type: {document_type or 'unknown'}.\n"
        + "Differences found (judge each by its index):\n"
        + json.dumps(differences, ensure_ascii=False, indent=2)
    )
    return _JUDGE_SYSTEM, _JUDGE_DEVELOPER, user
