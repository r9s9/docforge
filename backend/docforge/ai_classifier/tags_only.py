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

from ..common.textutil import slugify_field, value_kind
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, ElementType, FieldType, is_dynamic, needs_field
from ..schemas.extraction import DocumentExtraction, NormalizedElement
from .heuristic import looks_like_data_table

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


# Short labels that name a part of the document rather than say anything in it.
# They belong to the template's furniture: replacing "TABLE OF CONTENTS" with a
# sentence is never what anyone wanted.
_STRUCTURAL_LABELS = frozenset({
    "table of contents", "contents", "revisions", "revision history", "tables",
    "figures", "appendices", "appendix", "references", "bibliography", "index",
    "glossary", "abbreviations", "definitions", "annexes", "annex",
    "list of tables", "list of figures", "table of figures", "document history",
})
_STRUCTURAL_STYLE_HINTS = ("contents", "toc", "table of figures", "index")
_MAX_LABEL_CHARS = 24


def _is_structural_label(e: NormalizedElement) -> bool:
    """A section label that is part of the document's furniture, not its content."""
    text = " ".join((e.text or "").split())
    if not text or len(text) > _MAX_LABEL_CHARS:
        return False
    if text.strip(":").lower() in _STRUCTURAL_LABELS:
        return True
    style = (e.style_name or "").lower()
    # A very short label in a contents/TOC style is furniture even if we don't
    # know the word — corporate templates invent their own ("VERTEILER").
    return any(h in style for h in _STRUCTURAL_STYLE_HINTS) and len(text.split()) <= 3


def _is_exempt(e: NormalizedElement, c: ElementClassification | None) -> bool:
    """Nodes that keep their existing classification in tags-only mode."""
    if e.header_footer_scope is not None:
        return True  # headers/footers keep their (usually fixed/auto) content
    if (e.image_ref is not None or e.type == ElementType.IMAGE) and not (e.text or "").strip():
        return True  # a picture alone is swapped via its image field, not tagged

    if c is not None and c.classification == ClassificationType.AUTO_FIELD:
        return True  # page numbers / TOC render themselves
    if "auto_field" in e.semantic_hints or "toc" in e.semantic_hints:
        return True
    if not (e.text or "").strip() and e.type != ElementType.TABLE:
        return True  # nothing to templatize
    return False


def _keep_fixed(c: ElementClassification, reason: str) -> None:
    """Return a node to boilerplate, discarding any field the model gave it."""
    c.classification = ClassificationType.FIXED
    c.field_name = None
    c.field_type = None
    c.required = False
    c.optional = False
    c.rationale = f"{(c.rationale or '').rstrip()} [{reason}]".strip()


def _is_data_table(e: NormalizedElement) -> bool:
    """Whether a table repeats rows of the same kind, or is page layout."""
    return looks_like_data_table(e.table_structure)


def _cell_name(text: str) -> str:
    """Name a layout cell after what it *is*, not after the example's value.

    A cell reading "Document number" names itself; one reading "01.01.2001"
    would give "f_01_01_2001", which tells a later reader nothing. For those,
    the kind of value is the more useful name.
    """
    kind = value_kind(text)
    if kind != "text":
        return kind  # date / number / person — _unique adds the suffix
    return slugify_field(text, fallback="cell")


def _field_table_cells(
    extraction: DocumentExtraction,
    result: ClassificationResult,
    table: NormalizedElement,
    cls_by_node: dict[str, ElementClassification],
    used: set[str],
    section: str,
) -> set[str]:
    """Turn each non-empty cell of a layout table into its own field."""
    forced: set[str] = set()
    label = slugify_field(section or table.text or "cell", fallback="cell")
    for e in extraction.elements:
        if e.parent_node_id != table.node_id:
            continue
        text = (e.text or "").strip()
        if not text:
            continue  # spacing, or a cell holding only a picture
        c = cls_by_node.get(e.node_id)
        if c is None:
            c = ElementClassification(node_id=e.node_id, source=result.source or "heuristic")
            result.classifications.append(c)
            cls_by_node[e.node_id] = c
        if c.field_name and is_dynamic(c.classification):
            continue  # the model already named this cell
        name = _unique(f"{label}_{_cell_name(text)}", used)
        used.add(name)
        _force_dynamic(
            c,
            classification=ClassificationType.DYNAMIC_TEXT,
            field_type=(
                FieldType.MULTILINE_TEXT if len(text) > _MULTILINE_THRESHOLD else FieldType.TEXT
            ),
            name=name,
            section=section,
            text=text,
        )
        forced.add(e.node_id)
    return forced


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
    _mark_tags_only(c)


def _mark_tags_only(c: ElementClassification) -> None:
    """Tag a classification as tags-only-touched (idempotent).

    Used downstream by the template builder (to hide an empty field's whole
    paragraph rather than leave a blank line) and by the description-writing
    AI pass (to find nodes that still need a real, content-grounded blurb).
    """
    if "[tags_only]" not in (c.rationale or ""):
        c.rationale = f"{(c.rationale or '').rstrip()} [tags_only]".strip()


def enforce_tags_only(extraction: DocumentExtraction, result: ClassificationResult) -> set[str]:
    """Mutate ``result`` so every non-exempt text node is a dynamic field.

    Returns the set of node_ids that were force-fielded by this pass (i.e. the
    AI/heuristic engine had left them FIXED/UNKNOWN) — the caller can use this
    to target a follow-up AI description pass at exactly the fields that never
    got the model's attention.
    """
    cls_by_node = {c.node_id: c for c in result.classifications}
    forced: set[str] = set()

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
                    forced.add(_e.node_id)
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
                forced.add(e.node_id)

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
                _mark_tags_only(c)
            else:
                unfielded.append((e, c))
        flush_unfielded()

    for e in extraction.top_level_elements():
        c = cls_by_node[e.node_id]
        if _is_structural_label(e):
            # "TABLE OF CONTENTS", "REVISIONS", "FIGURES" — these name a part of
            # the document. Left as fields, a writer fills them with prose where
            # a one-word label belongs.
            flush_pending()
            _keep_fixed(c, "structural label")
            continue
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
                if not (c.description or "").strip():
                    c.description = _synth_description(section, e.text)
                _mark_tags_only(c)
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
                forced.add(e.node_id)
            continue

        if e.type == ElementType.TABLE:
            flush_pending()
            if c.classification == ClassificationType.REPEATABLE_TABLE and c.field_name:
                continue  # already a data table — the loop owns its cells
            if _is_data_table(e):
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
                forced.add(e.node_id)
            else:
                # A layout table (a cover block, an address panel). Its shape is
                # part of the design, so it keeps every row and each cell becomes
                # its own field instead of the whole table becoming a loop.
                forced.update(
                    _field_table_cells(extraction, result, e, cls_by_node, used, section)
                )
            continue

        if e.type in _GROUPABLE:
            pending.append((e, c))
            continue

        # Anything else with text (unknown kinds) — treat as a single paragraph.
        pending.append((e, c))
        flush_pending()

    flush_pending()

    # Final safety net: guarantee the invariant absolutely. Anything above could
    # in principle miss an edge case (a new ElementType, an unusual walk order);
    # this catches any surviving non-exempt node that still isn't a real field
    # and force-tags it individually, so "every text is tagged" always holds.
    for e in extraction.top_level_elements():
        c = cls_by_node[e.node_id]
        if _is_exempt(e, c) or _is_structural_label(e):
            continue
        if needs_field(c.classification) and c.field_name:
            continue
        if e.type == ElementType.TABLE:
            continue  # a layout table's cells carry its fields, not the table
        txt = e.text.strip()
        ftype = FieldType.MULTILINE_TEXT if len(txt) > _MULTILINE_THRESHOLD else FieldType.TEXT
        name = _unique(slugify_field(section or txt, fallback="content") + "_content", used)
        used.add(name)
        _force_dynamic(
            c,
            classification=ClassificationType.DYNAMIC_TEXT,
            field_type=ftype,
            name=name,
            section=section,
            text=txt,
        )
        forced.add(e.node_id)

    return forced
