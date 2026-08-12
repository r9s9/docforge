"""Prompt templates + strict response schemas for the three AI tasks (spec §10).

Each builder returns (system, developer, user) strings. Responses are validated
against the Pydantic models here before being mapped onto the domain schema.
"""

from __future__ import annotations

import json
import typing
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..assembler.richtext import RICH_FORMAT_SPEC
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


class LLMWrittenPlacement(_LenientLLMModel):
    """One field written by the document-writer agent."""

    field_name: str
    value: Any = None
    confidence: float = 0.8
    source_excerpt: str = ""
    ai_drafted: bool = False  # written from context rather than found verbatim
    ambiguous: bool = False
    alternatives: list[str] = Field(default_factory=list)
    note: str = ""


class LLMSectionSkip(_LenientLLMModel):
    """A section the writer deliberately left empty, and why."""

    section_key: str
    reason: str = ""


class LLMWriteResponse(_LenientLLMModel):
    """Output of the single-pass document writer: the whole document at once."""

    placements: list[LLMWrittenPlacement] = Field(default_factory=list)
    skipped_sections: list[LLMSectionSkip] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    unmapped_content: list[str] = Field(default_factory=list)
    notes: str = ""


class LLMComplianceVerdict(_LenientLLMModel):
    index: int
    material: bool = True  # a real compliance violation vs a benign/cosmetic diff
    severity: str = "warning"  # error | warning | info
    rationale: str = ""


class LLMComplianceJudgement(_LenientLLMModel):
    """The semantic judge's verdicts over a compliance check's differences."""

    verdicts: list[LLMComplianceVerdict] = Field(default_factory=list)
    summary: str = ""


class LLMFieldDescription(_LenientLLMModel):
    node_id: str
    description: str = ""


class LLMFieldDescriptions(_LenientLLMModel):
    """Output of the tags-only description pass: one blurb per forced field."""

    descriptions: list[LLMFieldDescription] = Field(default_factory=list)


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
    tags_only: bool = False,
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
    developer = _CLASSIFY_DEVELOPER + (_TAGS_ONLY_RULES if tags_only else "")
    return _CLASSIFY_SYSTEM, developer, user


# --- Tags-only mode: shared instruction block --------------------------------

_TAGS_ONLY_RULES = """\

TAGS-ONLY MODE — the final template must contain ONLY placeholders, no original text:
- Classify EVERY non-empty text element as DYNAMIC_* or REPEATABLE_* — nothing is
  FIXED except Word auto-fields (page numbers, TOC) and images.
- Headings => DYNAMIC_TEXT with field_type "text": the heading text itself is
  replaced by a tag. Name it after the heading's role, e.g. "project_overview_title".
- Body paragraphs => DYNAMIC_TEXT with field_type "multiline_text". When several
  CONSECUTIVE paragraphs cover ONE topic under the same heading, give them ALL the
  SAME field_name — they will be merged into one repeatable multi-paragraph field.
- List items => same rule as consecutive paragraphs (one shared field_name per list).
- Tables => REPEATABLE_TABLE.
- static_prefix and static_suffix MUST be null — no literal text survives.
- field_name: meaningful snake_case derived from the element's role in the document.
- description: describe what content belongs there and cite the original text as an
  example, e.g. "The report's executive summary (2-3 paragraphs). Example: 'During
  Q3 the team…'". These descriptions drive AI routing later — make them specific.
"""

_TAGS_ONLY_UNDERSTAND = (
    "\n\nTAGS-ONLY MODE: the user wants a fully-tagged template — assume every text "
    "element will become a fillable field. Your section read should propose good, "
    "role-based field names per section."
)

_TAGS_ONLY_CRITIQUE = (
    "\n\nTAGS-ONLY MODE: do NOT correct anything back to FIXED — every text element "
    "must remain a dynamic field. Focus on better names, types, and descriptions."
)


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
    tags_only: bool = False,
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
    developer = _UNDERSTAND_DEVELOPER + (_TAGS_ONLY_UNDERSTAND if tags_only else "")
    return _UNDERSTAND_SYSTEM, developer, user


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
    tags_only: bool = False,
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
    developer = _CRITIQUE_DEVELOPER + (_TAGS_ONLY_CRITIQUE if tags_only else "")
    return _CRITIQUE_SYSTEM, developer, user


# --- Tags-only: describe fields the enforcement pass had to force -----------
# `enforce_tags_only` runs AFTER the classification agent (incl. self-critique)
# already finished, so any field it force-creates never got the model's
# attention — it only carries a templated, content-citing placeholder
# description. This pass asks the (cheap) workhorse model for a real one.

_DESCRIBE_SYSTEM = (
    "You are DocForge's field-description writer. You are given template fields "
    "with their type and the ORIGINAL example text they replaced, and you write a "
    "short, specific, natural-language description of what content belongs in "
    "each field, grounded in the example. These descriptions are shown to template "
    "authors and used by another AI to route new content into the right field, so "
    "they must be concrete and specific — never generic boilerplate."
)

_DESCRIBE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "descriptions": [
    {"node_id": string, "description": string}
  ]
}

Rules:
- One or two sentences per field. Describe WHAT belongs there (its role/topic),
  not a generic phrase like "the value for this field" or "content for this section".
- Ground it in the example text: mention the KIND of content it held, e.g. "The
  session's learning objectives, written as 2-3 short bullet points" rather than
  "Text content for this section".
- Do not quote the example text verbatim at length — summarize its nature instead.
- Cover every node_id given. Output valid JSON only. No prose, no markdown.
"""


def build_describe_prompt(items: list[dict]) -> tuple[str, str, str]:
    """``items`` — [{node_id, field_name, field_type, classification, example_text}]."""
    user = (
        "Fields needing a description (write one per node_id):\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
        + "\n\nProduce a description for every node_id above."
    )
    return _DESCRIBE_SYSTEM, _DESCRIBE_DEVELOPER, user


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
- For a field whose "classification" is REPEATABLE_TABLE, "value" MUST be a list of
  objects keyed by the table's column field_names.
- For a field whose "classification" is REPEATABLE_SECTION, "value" SHOULD be a list
  of strings — one entry per distinct point/paragraph/bullet — when the content
  naturally breaks into more than one point. A single string is fine when there is
  only one point.
- Respect field types (dates as date-like strings, numbers as numbers/strings).
- If a required field has no corresponding content, list it in missing_required.
- Set ambiguous=true and populate alternatives when content could fit >1 field.
- Output valid JSON only. No prose, no markdown.

""" + RICH_FORMAT_SPEC + "\n"


def _fields_payload(
    fields: list[FieldDefinition], template_context: dict | None = None
) -> list[dict]:
    places = (template_context or {}).get("field_places") or {}
    out = []
    for f in fields:
        item: dict[str, Any] = {
            "field_name": f.field_name,
            "label": f.label,
            "type": f.field_type.value,
            "classification": f.classification.value,
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
        # Where this field sits in the document — the difference between filling
        # a form and writing into a specific place in a specific document.
        item.update(places.get(f.field_name, {}))
        out.append(item)
    return out


def _template_structure_block(template_context: dict | None) -> str:
    """A compact description of the document being filled, for the AI prompts."""
    if not template_context:
        return ""
    parts: list[str] = []
    doc_type = template_context.get("document_type")
    if doc_type:
        parts.append(f"The document you are filling in is: {doc_type}.")
    sections = template_context.get("sections") or []
    if sections:
        parts.append(
            "The document is organised into these sections, in order — place "
            "content where it belongs, and write each section to serve its "
            "stated purpose:\n"
            + json.dumps(sections, ensure_ascii=False, indent=2)
        )
    return "\n\n".join(parts)


def build_route_prompt(
    fields: list[FieldDefinition],
    *,
    raw_text: str | None = None,
    structured_data: dict | None = None,
    from_document: bool = False,
    template_context: dict | None = None,
) -> tuple[str, str, str]:
    parts = []
    structure = _template_structure_block(template_context)
    if structure:
        parts.append(structure)
    parts.append(
        "Template fields:\n"
        + json.dumps(_fields_payload(fields, template_context), ensure_ascii=False, indent=2)
    )
    if structured_data:
        parts.append(
            "Structured input (map/validate against the fields):\n"
            + json.dumps(structured_data, ensure_ascii=False, indent=2)
        )
    if raw_text:
        if from_document:
            parts.append(
                "Below is an outline of an uploaded document, with its own heading "
                "hierarchy, lists and tables preserved (# marks a heading level). Its "
                "structure will NOT match this template's, but it tells you what each "
                "piece of content is *for* — use it to place content into the template "
                "section that serves the same purpose, rather than matching on wording. "
                "Map only what genuinely fits a field; put the rest into "
                "unmapped_content, never force-fitting unrelated text or dumping a "
                "multi-topic block into one field. Where a block is marked truncated, "
                "call get_source_block with its id if you need the full text.\n\n"
                "Uploaded document outline:\n" + raw_text
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
- For a field whose "classification" is REPEATABLE_SECTION, "value" SHOULD be a
  list of strings — one entry per distinct point/paragraph/bullet — when the
  content naturally breaks into more than one point.
- For enum fields, the value MUST be one of the field's allowed_values.
- For a REQUIRED field with no value, DRAFT a sensible value from the supplied
  content and set ai_drafted=true with a lower confidence. Only leave it out and
  list it in still_missing when the content gives NO usable basis at all for it —
  prefer a reasonable, clearly-marked (ai_drafted=true) draft over leaving a
  section empty, since an empty required field disappears entirely from the
  generated document.
- NEVER fabricate specific facts (names, totals, dates) not supported by the content.
- Use normalize_date / normalize_number / validate_value to check before finalizing.
- Output valid JSON only. No prose, no markdown.

""" + RICH_FORMAT_SPEC + "\n"


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
    template_context: dict | None = None,
) -> tuple[str, str, str]:
    """Build the (system, developer, user) compose prompt.

    ``placements`` is the routed values to refine (objects with ``field_name`` /
    ``value``). ``source_text`` is the content they came from (notes or an
    extracted document), used to draft missing values and verify facts.
    ``template_context`` describes the document's sections so values are written
    to fit where they will actually appear.
    """
    current = {p.field_name: p.value for p in placements}
    parts = []
    structure = _template_structure_block(template_context)
    if structure:
        parts.append(structure)
    parts.extend([
        "Template fields:\n"
        + json.dumps(_fields_payload(fields, template_context), ensure_ascii=False, indent=2),
        "Currently routed values (refine these):\n"
        + json.dumps(current, ensure_ascii=False, default=str, indent=2),
    ])
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
# Document writer: read the whole template + all the content, write every field
# ---------------------------------------------------------------------------

_WRITER_SYSTEM = (
    "You are DocForge's document writer. You are given a template — what kind of "
    "document it is, its sections and what each is for — together with everything "
    "the user has supplied, and you write the whole document in one pass. You are "
    "not filling in a form field by field: you decide what belongs in each part of "
    "this specific document, and you write it so the finished result reads as one "
    "coherent piece. You never invent facts the supplied content does not support."
)

_WRITER_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "placements": [
    {"field_name": string,        // must be one of the template field names
     "value": any,                // the content; list of row-objects for table fields
     "confidence": number 0..1,
     "source_excerpt": string,    // the part of the input this came from
     "ai_drafted": boolean,       // true when you wrote it rather than found it
     "ambiguous": boolean,
     "alternatives": [string],
     "note": string}
  ],
  "skipped_sections": [
    {"section_key": string, "reason": string}   // sections you left empty on purpose
  ],
  "missing_required": [string],
  "unmapped_content": [string],
  "notes": string
}

Write the document, not the fields:
- Read everything first, then decide what belongs where. A field's place in the
  document — its section, the heading above it, the label beside it — tells you
  what it is for; the section's stated purpose tells you what to write there.
- Say each thing ONCE. Never repeat the same sentence, fact or phrasing in two
  fields; a summary summarises what the body says, it does not copy it.
- Keep one voice across the whole document: consistent tense, person and
  register, so the finished result does not read as assembled fragments.
- Write each section to fit its neighbours — do not restate what the section
  before it already established.
- A section with no real content is SKIPPED (list it in skipped_sections with a
  reason), never padded with filler or restated content from elsewhere.
- A boolean field named "include_…" switches an optional block on or off. Set it
  to false when the content clearly has nothing for that block; leave it alone
  otherwise.
- Only use field_name values from the template. Never invent fields.
- For REPEATABLE_TABLE fields, "value" MUST be a list of objects keyed by the
  table's column field_names.
- For REPEATABLE_SECTION fields, "value" SHOULD be a list of strings — one per
  distinct point — when the content naturally breaks into more than one.
- Respect field types: dates as ISO (YYYY-MM-DD) unless the description says
  otherwise, numbers normalised, enum values from allowed_values only.
- Set ai_drafted=true with lower confidence for anything you wrote from context
  rather than found in the content. NEVER fabricate specific facts (names,
  totals, dates) the content does not support — leave those out and list the
  field in missing_required instead.
- Output valid JSON only. No prose, no markdown.

""" + RICH_FORMAT_SPEC + "\n"


def build_writer_prompt(
    fields: list[FieldDefinition],
    *,
    template_context: dict | None = None,
    source_outline: str = "",
    raw_text: str | None = None,
    structured_data: dict | None = None,
    learned_hints: str = "",
    review_findings: list[dict] | None = None,
    prior_values: dict | None = None,
) -> tuple[str, str, str]:
    """Build the (system, developer, user) prompt for the one-pass writer.

    Everything needed is in the user message: tools are an optimisation, and the
    agentic loop degrades to a single call on providers without tool support, so
    the prompt must stand on its own.
    """
    parts: list[str] = []
    structure = _template_structure_block(template_context)
    if structure:
        parts.append(structure)
    if learned_hints:
        parts.append(learned_hints)
    parts.append(
        "Template fields:\n"
        + json.dumps(_fields_payload(fields, template_context), ensure_ascii=False, indent=2)
    )
    if structured_data:
        parts.append(
            "Values the user supplied directly (keep these unless they are clearly "
            "malformed):\n" + json.dumps(structured_data, ensure_ascii=False, default=str, indent=2)
        )
    if source_outline:
        parts.append(
            "Content to work from — an outline of an uploaded document, with its own "
            "heading hierarchy, lists and tables preserved (# marks a heading level). "
            "Its structure will NOT match this template's; use it to understand what "
            "each piece of content is for, then place it where it serves the same "
            "purpose here. Where a block is marked truncated, call get_source_block "
            "with its id if you need the full text.\n\n" + source_outline
        )
    elif raw_text:
        parts.append("Content to work from (the user's notes):\n" + raw_text[:_COMPOSE_SOURCE_TEXT_CAP])
    if prior_values:
        parts.append(
            "Your previous draft (revise it — keep what is good):\n"
            + json.dumps(prior_values, ensure_ascii=False, default=str, indent=2)
        )
    if review_findings:
        parts.append(
            "A review of the document you just produced found these problems. Fix "
            "every one of them in this revision:\n"
            + json.dumps(review_findings, ensure_ascii=False, indent=2)
        )
    parts.append("Write the document now.")
    return _WRITER_SYSTEM, _WRITER_DEVELOPER, "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Refine: change the draft in the way the user just asked for, and only that
# ---------------------------------------------------------------------------


class LLMRefineResponse(_LenientLLMModel):
    """A conversational edit: what changed, plus a sentence saying what you did."""

    reply: str = ""
    updates: list[LLMComposedValue] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)  # fields to clear
    skip_sections: list[str] = Field(default_factory=list)  # sections to leave out


_REFINE_SYSTEM = (
    "You are DocForge's document editor, working with someone on a draft that is "
    "already written. They tell you what to change; you change exactly that and "
    "leave everything else alone. You reply the way an editor would — one or two "
    "sentences saying what you did — never with the document itself."
)

_REFINE_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "reply": string,                  // 1-2 sentences to the user: what you changed
  "updates": [
    {"field_name": string,          // ONLY fields you are changing
     "value": any,
     "confidence": number 0..1,
     "ai_drafted": boolean,
     "note": string}
  ],
  "removed": [string],              // fields to clear entirely
  "skip_sections": [string]         // section_keys to leave out of the document
}

Rules:
- Change ONLY what was asked. A field you are not changing must NOT appear in
  updates — an unchanged field echoed back is a bug, not a no-op.
- "Shorten the summary" means rewrite that one field, not every field.
- When the request is ambiguous, make the smallest reasonable change and say in
  the reply what you assumed.
- When a request cannot be satisfied (the content does not support it, or no
  such field exists), change nothing and explain why in the reply.
- Keep the document's established voice and tense; do not restyle untouched
  parts by side effect.
- Respect field types: dates as ISO (YYYY-MM-DD) unless the description says
  otherwise, numbers normalised, enum values from allowed_values only.
- NEVER invent facts (names, totals, dates) the content does not support.
- Output valid JSON only. No prose, no markdown.

""" + RICH_FORMAT_SPEC + "\n"


def build_refine_prompt(
    fields: list[FieldDefinition],
    messages: list,
    current_values: dict,
    *,
    template_context: dict | None = None,
    source_context: str = "",
) -> tuple[str, str, str]:
    """Build the (system, developer, user) prompt for one refine turn.

    ``messages`` is the conversation so far (objects with ``role``/``content``);
    the last user message is the instruction to act on.
    """
    parts: list[str] = []
    structure = _template_structure_block(template_context)
    if structure:
        parts.append(structure)
    parts.append(
        "Template fields:\n"
        + json.dumps(_fields_payload(fields, template_context), ensure_ascii=False, indent=2)
    )
    parts.append(
        "The current draft (what the document says right now):\n"
        + json.dumps(current_values, ensure_ascii=False, default=str, indent=2)
    )
    if source_context:
        parts.append(
            "The content this draft was written from — stay faithful to it:\n"
            + source_context[:_COMPOSE_SOURCE_TEXT_CAP]
        )
    history = [
        f"{getattr(m, 'role', '') or m.get('role', '')}: "
        f"{getattr(m, 'content', '') or m.get('content', '')}"
        for m in messages
    ]
    if history:
        parts.append("The conversation so far:\n" + "\n".join(history))
    parts.append("Make the change the last message asks for.")
    return _REFINE_SYSTEM, _REFINE_DEVELOPER, "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Render review: read the assembled document back and find what reads wrong
# ---------------------------------------------------------------------------


class LLMRenderFinding(_LenientLLMModel):
    kind: str = "other"  # empty_section | duplicate | misplaced | format | other
    field_name: str | None = None
    section_key: str | None = None
    message: str = ""
    severity: str = "warning"  # error | warning | info


class LLMRenderReview(_LenientLLMModel):
    """What a reader notices when the finished document is read back."""

    findings: list[LLMRenderFinding] = Field(default_factory=list)


_REVIEW_SYSTEM = (
    "You are DocForge's final reader. You are shown a document that has just been "
    "assembled from a template and you read it the way its recipient would, "
    "reporting only what would actually bother them: a section left empty, the "
    "same thing said twice, content sitting under the wrong heading, or text "
    "whose shape is wrong for where it is. You do not rewrite it and you do not "
    "nitpick wording."
)

_REVIEW_DEVELOPER = """\
Return ONLY a JSON object with this shape:
{
  "findings": [
    {"kind": one of ["empty_section","duplicate","misplaced","format","other"],
     "field_name": string or null,     // the field responsible, when you can tell
     "section_key": string or null,
     "message": short string,          // what is wrong, in plain words
     "severity": one of ["error","warning","info"]}
  ]
}

Rules:
- Report a problem only if a reader would notice it. An empty document with
  nothing supplied is not a finding; a section that promises content and
  delivers none is.
- "duplicate" means the same substance appears twice, not two mentions of the
  same subject.
- Do not report the template's own fixed boilerplate as a problem.
- severity "error" is reserved for things that make the document unusable or
  self-contradictory. Prefer "warning" or "info".
- An empty findings list is the correct answer for a good document.
- Output valid JSON only. No prose, no markdown.
"""


def build_render_review_prompt(
    blocks: list[dict],
    *,
    template_context: dict | None = None,
    placed_fields: list[str] | None = None,
    skipped_sections: list[dict] | None = None,
) -> tuple[str, str, str]:
    """Build the (system, developer, user) prompt for reviewing rendered output."""
    parts: list[str] = []
    structure = _template_structure_block(template_context)
    if structure:
        parts.append(structure)
    parts.append(
        "The assembled document, in order:\n"
        + json.dumps(blocks, ensure_ascii=False, indent=2)[:_COMPOSE_SOURCE_TEXT_CAP]
    )
    if placed_fields:
        parts.append("Fields that were filled in: " + ", ".join(placed_fields))
    if skipped_sections:
        parts.append(
            "Sections deliberately left empty (do NOT report these as problems):\n"
            + json.dumps(skipped_sections, ensure_ascii=False)
        )
    parts.append("Read it and report what a recipient would notice.")
    return _REVIEW_SYSTEM, _REVIEW_DEVELOPER, "\n\n".join(parts)


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
