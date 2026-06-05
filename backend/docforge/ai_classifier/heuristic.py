"""Deterministic, rule-based classifier (spec §5 ai_classifier, §9 tasks A & B).

This is the always-available fallback used when no LLM is configured. It encodes
the document-intelligence rules so behaviour is testable and identical offline:

  * diff IDENTICAL            -> FIXED
  * diff PARTIAL_CHANGE       -> typed dynamic field (label kept static)
  * diff CHANGED              -> fully dynamic field
  * table rows vary           -> REPEATABLE_TABLE
  * Word field / page number  -> AUTO_FIELD
  * single document           -> hints (labels, dates, numbers, tables)

The LLM classifier (llm.py) produces the *same* schema and can override/enrich
this when configured.
"""

from __future__ import annotations

from ..common.textutil import slugify_field, value_kind
from ..schemas.classification import (
    ClassificationResult,
    ElementClassification,
    SectionUnderstanding,
)
from ..schemas.diff import DiffRunResult, NodeDiff
from ..schemas.enums import ClassificationType, DiffStatus, ElementType, FieldType
from ..schemas.extraction import DocumentExtraction, NormalizedElement

_PERSON_LABEL_HINTS = (
    "by", "author", "prepared", "auditor", "manager", "owner",
    "contact", "approver", "reviewer", "officer", "lead", "signed",
)


def _unique(base: str, used: set[str]) -> str:
    name = base or "field"
    if name not in used:
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    return f"{name}_{i}"


def _label_is_personish(label: str) -> bool:
    low = (label or "").lower()
    return any(h in low for h in _PERSON_LABEL_HINTS)


def _kind_to_classification(
    kind: str, label: str
) -> tuple[ClassificationType, FieldType]:
    if kind == "date":
        return ClassificationType.DYNAMIC_DATE, FieldType.DATE
    if kind == "number":
        return ClassificationType.DYNAMIC_NUMBER, FieldType.NUMBER
    if kind == "person":
        # A value can *look* like a name but a non-person label (e.g. "Project
        # Name", "Bill To") means it's really free text.
        if _label_is_personish(label) or not label:
            return ClassificationType.DYNAMIC_PERSON, FieldType.PERSON
        return ClassificationType.DYNAMIC_TEXT, FieldType.TEXT
    return ClassificationType.DYNAMIC_TEXT, FieldType.TEXT


def _validation_hints(kind: str, samples: list[str]) -> list[str]:
    if kind == "date":
        return ["Expected a date (e.g. YYYY-MM-DD)"]
    if kind == "number":
        return ["Expected a numeric value"]
    if kind == "person":
        return ["Expected a person name"]
    return []


def _guess_doc_type(top: list[NormalizedElement]) -> str:
    for e in top:
        if "all_caps" in e.semantic_hints and 3 < len(e.text.strip()) < 80:
            return e.text.strip().title()
    for e in top:
        if e.type == ElementType.HEADING and e.text.strip():
            return e.text.strip().title()
    return "Document"


def _dynamic_from_diff(
    e: NormalizedElement, nd: NodeDiff, section_title: str, used: set[str]
) -> ElementClassification:
    label = ""
    if nd.static_prefix:
        label = nd.static_prefix.strip().rstrip(":").strip()
    base = slugify_field(label) if label else slugify_field(section_title or e.text, fallback="field")
    name = _unique(base, used)
    kind = nd.detected_kind or value_kind(e.text)
    cls, ftype = _kind_to_classification(kind, label)
    required = "absent" not in (nd.notes or "")
    desc = f"Dynamic {kind} value" + (f" for '{label}'" if label else "")
    return ElementClassification(
        node_id=e.node_id,
        classification=cls,
        field_name=name,
        field_type=ftype,
        description=desc,
        required=required,
        confidence=nd.confidence,
        validation_hints=_validation_hints(kind, nd.variable_parts),
        static_prefix=nd.static_prefix,
        static_suffix=nd.static_suffix,
        source="heuristic",
        rationale=f"diff:{nd.status.value}",
    )


def _classify_table(
    e: NormalizedElement, nd: NodeDiff | None, section_title: str, used: set[str]
) -> ElementClassification:
    ts = e.table_structure
    n_data = (ts.n_rows - 1) if ts and ts.n_rows else 0

    if nd and nd.status == DiffStatus.IDENTICAL:
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.FIXED,
            required=False,
            confidence=nd.confidence,
            source="heuristic",
            rationale="table identical across samples",
        )

    if nd is not None:
        repeatable = nd.row_count_variable or nd.status in (
            DiffStatus.ROW_COUNT_CHANGED,
            DiffStatus.CHANGED,
        )
        conf = nd.confidence
    else:
        repeatable = n_data >= 1
        conf = 0.6 if n_data >= 2 else 0.45

    if not repeatable:
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.FIXED,
            required=False,
            confidence=conf,
            source="heuristic",
            rationale="static table",
        )

    name = _unique(slugify_field(section_title or "rows", fallback="rows"), used)
    cols = ts.headers if ts else []
    return ElementClassification(
        node_id=e.node_id,
        classification=ClassificationType.REPEATABLE_TABLE,
        field_name=name,
        field_type=FieldType.TABLE,
        description=f"Repeatable table rows for '{section_title or name}'",
        required=True,
        confidence=conf,
        validation_hints=[f"columns: {', '.join(cols)}"] if cols else [],
        source="heuristic",
        rationale="table rows vary across samples" if nd else "multi-row data table",
    )


def _classify_single_doc(
    e: NormalizedElement, section_title: str, used: set[str]
) -> ElementClassification:
    txt = e.text.strip()
    # Labeled "Key: value" lines -> dynamic value with the label kept static.
    if ":" in txt:
        label, _, value = txt.partition(":")
        value = value.strip()
        if value:
            kind = value_kind(value)
            cls, ftype = _kind_to_classification(kind, label)
            name = _unique(slugify_field(label), used)
            return ElementClassification(
                node_id=e.node_id,
                classification=cls,
                field_name=name,
                field_type=ftype,
                description=f"Value for '{label.strip()}'",
                required=True,
                confidence=0.55,
                static_prefix=f"{label}: ",
                static_suffix="",
                validation_hints=_validation_hints(kind, [value]),
                source="heuristic",
                rationale="single-doc labeled value",
            )

    if "all_caps" in e.semantic_hints and len(txt) < 80:
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.FIXED,
            required=False,
            confidence=0.6,
            source="heuristic",
            rationale="all-caps title",
        )

    kind = value_kind(txt)
    if kind in ("date", "number", "person") and len(txt) < 60:
        cls, ftype = _kind_to_classification(kind, section_title)
        name = _unique(slugify_field(section_title or kind, fallback=kind), used)
        return ElementClassification(
            node_id=e.node_id,
            classification=cls,
            field_name=name,
            field_type=ftype,
            description=f"Standalone {kind} value",
            required=True,
            confidence=0.5,
            validation_hints=_validation_hints(kind, [txt]),
            source="heuristic",
            rationale="single-doc typed token",
        )

    return ElementClassification(
        node_id=e.node_id,
        classification=ClassificationType.FIXED,
        required=False,
        confidence=0.5,
        source="heuristic",
        rationale="single-doc default fixed",
    )


def _classify_element(
    e: NormalizedElement, nd: NodeDiff | None, section_title: str, used: set[str]
) -> ElementClassification:
    # AUTO fields (page numbers, TOC, Word fields) — leave untouched.
    if "auto_field" in e.semantic_hints or "toc" in e.semantic_hints:
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.AUTO_FIELD,
            required=False,
            confidence=0.9,
            source="heuristic",
            rationale="Word field / auto content",
        )

    if nd is not None and nd.status == DiffStatus.IMAGE_CHANGED:
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.UNKNOWN,
            description="Image differs across samples (image templating is out of scope in v1)",
            required=False,
            confidence=0.4,
            source="heuristic",
            rationale="varying image",
        )

    if e.type == ElementType.TABLE:
        return _classify_table(e, nd, section_title, used)

    if e.type == ElementType.HEADING:
        if nd is not None and nd.status in (DiffStatus.CHANGED, DiffStatus.PARTIAL_CHANGE):
            return _dynamic_from_diff(e, nd, section_title, used)
        return ElementClassification(
            node_id=e.node_id,
            classification=ClassificationType.FIXED,
            required=False,
            confidence=nd.confidence if nd else 0.7,
            source="heuristic",
            rationale="heading / structural label",
        )

    if nd is not None:
        if nd.status == DiffStatus.IDENTICAL:
            return ElementClassification(
                node_id=e.node_id,
                classification=ClassificationType.FIXED,
                required=False,
                confidence=nd.confidence,
                source="heuristic",
                rationale="identical across samples",
            )
        if nd.status in (DiffStatus.PARTIAL_CHANGE, DiffStatus.CHANGED):
            return _dynamic_from_diff(e, nd, section_title, used)

    return _classify_single_doc(e, section_title, used)


def classify_heuristic(
    extraction: DocumentExtraction, diff: DiffRunResult | None = None
) -> ClassificationResult:
    """Classify every element of the representative extraction (offline)."""
    top = extraction.top_level_elements()
    diff_by_node = {d.representative_node_id: d for d in (diff.node_diffs if diff else [])}

    # Section assignment: each heading opens a section that following nodes join.
    section_of: dict[str, tuple[str, str]] = {}
    sections: dict[str, SectionUnderstanding] = {}
    cur_key, cur_title = "preamble", "Preamble"
    sections[cur_key] = SectionUnderstanding(
        section_key=cur_key, title=cur_title, purpose="Top-of-document content."
    )
    for e in top:
        if e.type == ElementType.HEADING:
            cur_key, cur_title = e.node_id, e.text.strip() or "Section"
            sections[cur_key] = SectionUnderstanding(
                section_key=cur_key,
                title=cur_title,
                purpose=f"Content belonging to the '{cur_title}' section.",
            )
        section_of[e.node_id] = (cur_key, cur_title)

    used: set[str] = set()
    classifications: list[ElementClassification] = []
    for e in top:
        skey, stitle = section_of.get(e.node_id, ("preamble", "Preamble"))
        nd = diff_by_node.get(e.node_id)
        c = _classify_element(e, nd, stitle, used)
        # Content present in some examples but not others becomes optional
        # (the builder wraps it in a conditional). Auto fields stay as-is.
        if nd is not None and nd.is_optional and c.classification != ClassificationType.AUTO_FIELD:
            c.optional = True
        classifications.append(c)
        if c.field_name:
            used.add(c.field_name)
            sections[skey].field_names.append(c.field_name)

    # Everything nested inside a table/cell is fixed (its table owns it).
    for e in extraction.elements:
        if e.parent_node_id is not None:
            classifications.append(
                ElementClassification(
                    node_id=e.node_id,
                    classification=ClassificationType.FIXED,
                    required=False,
                    confidence=0.5,
                    source="heuristic",
                    rationale="inside table cell",
                )
            )

    return ClassificationResult(
        extraction_document_id=extraction.document_id,
        classifications=classifications,
        sections=list(sections.values()),
        document_type_guess=_guess_doc_type(top),
        source="heuristic",
    )
