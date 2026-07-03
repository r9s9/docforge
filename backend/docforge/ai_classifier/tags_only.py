"""Tags-only mode: guarantee that EVERY text element becomes a fillable field.

In tags-only mode the published template must contain only placeholders — no
original prose survives. The AI passes are instructed to classify everything as
dynamic with meaningful names, but this deterministic post-pass is the safety
net that enforces the invariant regardless of which engine produced the result
(LLM, heuristic, or the heuristic fallback after an AI failure).

Grouping: one field per heading and per table; a run of >= 2 consecutive body
paragraphs / list items under one heading collapses into ONE repeatable-section
field (all nodes share the field name), so an 80-paragraph document yields a
handful of section fields instead of 80 one-off fields.
"""

from __future__ import annotations

from ..common.textutil import slugify_field
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, ElementType, FieldType, is_dynamic
from ..schemas.extraction import DocumentExtraction, NormalizedElement

# Body text longer than this becomes a multiline field rather than a one-liner.
_MULTILINE_THRESHOLD = 120

_GROUPABLE = (ElementType.PARAGRAPH, ElementType.LIST_ITEM)


def _unique(base: str, used: set[str]) -> str:
    name = base or "field"
    if name not in used:
        return name
    i = 2
    while f"{name}_{i}" in used:
        i += 1
    return f"{name}_{i}"


def _synth_description(section: str, text: str) -> str:
    sample = " ".join(text.split())
    if len(sample) > 120:
        sample = sample[:120].rstrip() + "…"
    where = f'the "{section}" section' if section else "the document"
    return f"Content for {where}. Original example: “{sample}”"


def _is_exempt(e: NormalizedElement, c: ElementClassification | None) -> bool:
    """Nodes that keep their existing classification in tags-only mode."""
    if e.header_footer_scope is not None:
        return True  # headers/footers keep their (usually fixed/auto) content
    if e.image_ref is not None or e.type == ElementType.IMAGE:
        return True  # images are swapped via image fields, never text tags
    if c is not None and c.classification == ClassificationType.AUTO_FIELD:
        return True  # page numbers / TOC render themselves
    if "auto_field" in e.semantic_hints or "toc" in e.semantic_hints:
        return True
    if not (e.text or "").strip() and e.type != ElementType.TABLE:
        return True  # nothing to templatize
    return False


def _force_dynamic(
    c: ElementClassification,
    *,
    classification: ClassificationType,
    field_type: FieldType,
    name: str,
    section: str,
    text: str,
) -> None:
    c.classification = classification
    c.field_name = name
    c.field_type = field_type
    c.required = True
    c.optional = False
    c.static_prefix = None
    c.static_suffix = None
    if not (c.description or "").strip():
        c.description = _synth_description(section, text)
    c.rationale = f"{c.rationale} [tags_only]".strip()


def enforce_tags_only(extraction: DocumentExtraction, result: ClassificationResult) -> None:
    """Mutate ``result`` so every non-exempt text node is a dynamic field."""
    cls_by_node = {c.node_id: c for c in result.classifications}

    # Ensure every top-level node has a classification entry to mutate.
    for e in extraction.top_level_elements():
        if e.node_id not in cls_by_node:
            c = ElementClassification(node_id=e.node_id, source=result.source or "heuristic")
            result.classifications.append(c)
            cls_by_node[e.node_id] = c

    used: set[str] = {
        c.field_name for c in result.classifications if c.field_name
    }

    # Walk in document order, tracking the current section title and grouping
    # consecutive groupable body nodes.
    section = ""
    pending: list[tuple[NormalizedElement, ElementClassification]] = []

    def flush_pending() -> None:
        """Assign the buffered paragraph/list run to field(s)."""
        nonlocal pending
        if not pending:
            return
        run = pending
        pending = []
        # Nodes the AI already fielded keep their own names; only consecutive
        # *unfielded* nodes are grouped. Split the run accordingly.
        unfielded: list[tuple[NormalizedElement, ElementClassification]] = []

        def flush_unfielded() -> None:
            nonlocal unfielded
            chunk = unfielded
            unfielded = []
            if not chunk:
                return
            if len(chunk) >= 2:
                # One repeatable section: every node shares the field name.
                name = _unique(slugify_field(section or "body", fallback="body") + "_body", used)
                used.add(name)
                joined = " ".join(e.text.strip() for e, _ in chunk[:3])
                for _e, c in chunk:
                    _force_dynamic(
                        c,
                        classification=ClassificationType.REPEATABLE_SECTION,
                        field_type=FieldType.MULTILINE_TEXT,
                        name=name,
                        section=section,
                        text=joined,
                    )
            else:
                e, c = chunk[0]
                txt = e.text.strip()
                ftype = (
                    FieldType.MULTILINE_TEXT
                    if len(txt) > _MULTILINE_THRESHOLD
                    else FieldType.TEXT
                )
                name = _unique(slugify_field(section or txt, fallback="body") + "_body", used)
                used.add(name)
                _force_dynamic(
                    c,
                    classification=ClassificationType.DYNAMIC_TEXT,
                    field_type=ftype,
                    name=name,
                    section=section,
                    text=txt,
                )

        for e, c in run:
            if c.field_name and (is_dynamic(c.classification) or c.classification == ClassificationType.REPEATABLE_SECTION):
                flush_unfielded()
                # Already a named dynamic field (AI-directed) — just enforce the
                # no-literal-text invariant.
                c.static_prefix = None
                c.static_suffix = None
                c.required = True
                c.optional = False
                if not (c.description or "").strip():
                    c.description = _synth_description(section, e.text)
            else:
                unfielded.append((e, c))
        flush_unfielded()

    for e in extraction.top_level_elements():
        c = cls_by_node[e.node_id]
        if _is_exempt(e, c):
            flush_pending()
            continue

        if e.type == ElementType.HEADING:
            flush_pending()
            section = e.text.strip() or section
            if c.field_name and is_dynamic(c.classification):
                c.static_prefix = None
                c.static_suffix = None
                c.required = True
                c.optional = False
            else:
                name = _unique(
                    slugify_field(section or "section", fallback="section") + "_title", used
                )
                used.add(name)
                _force_dynamic(
                    c,
                    classification=ClassificationType.DYNAMIC_TEXT,
                    field_type=FieldType.TEXT,
                    name=name,
                    section=section,
                    text=e.text.strip(),
                )
            continue

        if e.type == ElementType.TABLE:
            flush_pending()
            if c.classification != ClassificationType.REPEATABLE_TABLE or not c.field_name:
                name = c.field_name or _unique(
                    slugify_field(section or "rows", fallback="rows") + "_rows", used
                )
                used.add(name)
                headers = e.table_structure.headers if e.table_structure else []
                _force_dynamic(
                    c,
                    classification=ClassificationType.REPEATABLE_TABLE,
                    field_type=FieldType.TABLE,
                    name=name,
                    section=section,
                    text=", ".join(headers) or "table",
                )
            continue

        if e.type in _GROUPABLE:
            pending.append((e, c))
            continue

        # Anything else with text (unknown kinds) — treat as a single paragraph.
        pending.append((e, c))
        flush_pending()

    flush_pending()
