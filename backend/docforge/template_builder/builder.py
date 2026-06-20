"""template_builder — turn a representative DOCX + classifications into a
docxtpl template (spec §6, §11).

Layout is preserved by *modifying the representative document's XML in place*
rather than rebuilding it: FIXED/AUTO content is left untouched, dynamic values
are replaced with ``{{ field }}`` (keeping any static label prefix/suffix), and
repeatable tables get a ``{%tr for ... %}`` / ``{%tr endfor %}`` loop using the
verified 3-row pattern (for-row / template-row / endfor-row).

When in-place run rewriting cannot express a case cleanly, the OOXML fallback in
``ooxml_ops.py`` provides direct lxml manipulation.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..ai_classifier import classify, derive_field_definitions
from ..ai_classifier.fields import include_field_name
from ..multi_doc_differ import diff_documents, pick_representative
from ..schemas.classification import ClassificationResult
from ..schemas.enums import ClassificationType, FieldType, is_dynamic
from ..schemas.extraction import DocumentExtraction
from ..schemas.template import FieldDefinition
from ..structure_normalizer import build_extraction, walk_document

logger = logging.getLogger("docforge.template_builder")

# Jinja loop variable used inside repeatable tables/sections.
_LOOP_VAR = "item"

# A field name must be a valid Jinja/Python identifier to become a placeholder
# ({{ name }}); anything else (spaces, dots, a leading digit) makes docxtpl fail
# to compile the whole template. Names are sanitized upstream, but this is the
# last-line guard so one stray name can never crash a build/preview.
_VALID_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str | None) -> str | None:
    return name if name and _VALID_IDENT.match(name) else None


def _marker_paragraph_xml(text: str):
    """A bare <w:p> carrying a docxtpl control tag (e.g. {%p if x %})."""
    p = OxmlElement("w:p")
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    p.append(run)
    return p


def _insert_marker_before(paragraph: Paragraph, text: str) -> None:
    paragraph._p.addprevious(_marker_paragraph_xml(text))


def _insert_marker_after(paragraph: Paragraph, text: str) -> None:
    paragraph._p.addnext(_marker_paragraph_xml(text))


# --- run-formatting helpers -------------------------------------------------
def _run_format_at(paragraph: Paragraph, offset: int) -> dict:
    """Capture character formatting from the run covering ``offset``."""
    runs = paragraph.runs
    if not runs:
        return {}
    acc = 0
    chosen = runs[0]
    for r in runs:
        length = len(r.text or "")
        if acc <= offset < acc + length:
            chosen = r
            break
        acc += length
    else:
        chosen = runs[-1]
    f = chosen.font
    fmt: dict = {"bold": f.bold, "italic": f.italic, "underline": f.underline, "name": f.name}
    try:
        fmt["size"] = f.size
    except (AttributeError, ValueError):
        fmt["size"] = None
    try:
        fmt["color"] = f.color.rgb if (f.color is not None and f.color.rgb is not None) else None
    except (AttributeError, ValueError):
        fmt["color"] = None
    return fmt


def _clear_runs(paragraph: Paragraph) -> None:
    for r in list(paragraph.runs):
        r._element.getparent().remove(r._element)


def _append_run(paragraph: Paragraph, text: str, fmt: dict):
    run = paragraph.add_run(text)
    if fmt:
        if fmt.get("bold") is not None:
            run.font.bold = fmt["bold"]
        if fmt.get("italic") is not None:
            run.font.italic = fmt["italic"]
        if fmt.get("underline") is not None:
            run.font.underline = fmt["underline"]
        if fmt.get("name"):
            run.font.name = fmt["name"]
        if fmt.get("size"):
            run.font.size = fmt["size"]
        if fmt.get("color") is not None:
            try:
                run.font.color.rgb = fmt["color"]
            except (AttributeError, ValueError):
                pass
    return run


def _templatize_paragraph(paragraph: Paragraph, prefix: str, expr: str, suffix: str) -> None:
    """Rewrite a paragraph to ``prefix{{ field }}suffix`` keeping run formatting."""
    full = paragraph.text or ""
    fmt_prefix = _run_format_at(paragraph, 0)
    fmt_value = _run_format_at(paragraph, len(prefix))
    fmt_suffix = _run_format_at(paragraph, max(0, len(full) - len(suffix)))
    _clear_runs(paragraph)
    if prefix:
        _append_run(paragraph, prefix, fmt_prefix)
    _append_run(paragraph, expr, fmt_value)
    if suffix:
        _append_run(paragraph, suffix, fmt_suffix)


def _set_cell_expr(cell, expr: str) -> None:
    """Set a table cell to a single ``expr``, preserving the first run's format."""
    paras = cell.paragraphs
    if not paras:
        cell.text = expr
        return
    first = paras[0]
    fmt = _run_format_at(first, 0)
    _clear_runs(first)
    _append_run(first, expr, fmt)
    for extra in paras[1:]:
        extra._element.getparent().remove(extra._element)


def _tag_row(row, text: str) -> None:
    seen: set[int] = set()
    for i, cell in enumerate(row.cells):
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        cell.text = text if i == 0 else ""


def _templatize_table(table: Table, field_name: str, columns: list) -> None:
    """Convert the first data row into a repeated row driven by ``field_name``."""
    rows = table.rows
    if len(rows) < 2:
        return  # header only — nothing to repeat
    template_row = rows[1]

    # Rewrite each physical cell of the template row to {{ item.col }}.
    seen: set[int] = set()
    for ci, cell in enumerate(template_row.cells):
        key = id(cell._tc)
        if key in seen:
            continue
        seen.add(key)
        col = columns[ci].field_name if ci < len(columns) else f"col{ci + 1}"
        _set_cell_expr(cell, f"{{{{ {_LOOP_VAR}.{col} }}}}")

    # Drop the remaining example data rows (index >= 2).
    for extra in list(table.rows)[2:]:
        extra._tr.getparent().remove(extra._tr)

    # Wrap the template row with for/endfor marker rows (verified pattern).
    for_row = table.add_row()
    _tag_row(for_row, f"{{%tr for {_LOOP_VAR} in {field_name} %}}")
    endfor_row = table.add_row()
    _tag_row(endfor_row, "{%tr endfor %}")
    template_row._tr.addprevious(for_row._tr)
    template_row._tr.addnext(endfor_row._tr)


def _templatize_repeatable_paragraph(paragraph: Paragraph, field_name: str) -> None:
    """Turn a paragraph into a repeated paragraph: one rendered per list item."""
    _templatize_paragraph(paragraph, "", f"{{{{ {_LOOP_VAR} }}}}", "")
    _insert_marker_before(paragraph, f"{{%p for {_LOOP_VAR} in {field_name} %}}")
    _insert_marker_after(paragraph, "{%p endfor %}")


def _wrap_optional(paragraph: Paragraph, include_name: str) -> None:
    """Wrap a paragraph so it only renders when ``include_name`` is truthy."""
    _insert_marker_before(paragraph, f"{{%p if {include_name} %}}")
    _insert_marker_after(paragraph, "{%p endif %}")


# --- main builder -----------------------------------------------------------
def build_template_docx(
    representative_docx_path: str,
    result: ClassificationResult,
    fields: list[FieldDefinition],
) -> bytes:
    """Produce the template.docx bytes for a representative document."""
    doc = Document(str(representative_docx_path))
    nodes = walk_document(doc)

    cls_by_node = {c.node_id: c for c in result.classifications}
    # Map node -> its VALUE field (skip the boolean "include_*" toggles, which
    # also carry the node id but must not be used as the value placeholder).
    fd_by_node: dict[str, FieldDefinition] = {}
    for f in fields:
        if f.field_type == FieldType.BOOLEAN:
            continue
        for nid in f.node_ids:
            fd_by_node[nid] = f

    for wn in nodes:
        cls = cls_by_node.get(wn.node_id)
        if cls is None:
            continue

        # Repeatable table.
        if cls.classification == ClassificationType.REPEATABLE_TABLE and wn.kind == "table":
            fd = fd_by_node.get(wn.node_id)
            name = _safe_ident(fd.field_name) if fd else None
            if name:
                _templatize_table(wn.obj, name, fd.columns)
            elif fd:
                logger.warning("skipping table field with unsafe name %r", fd.field_name)
            continue

        if wn.kind != "paragraph":
            continue

        para = wn.obj
        fd = fd_by_node.get(wn.node_id)
        # Compute the optional toggle name from the ORIGINAL text (before edits).
        include_name = _safe_ident(include_field_name(cls, para)) if cls.optional else None

        if cls.classification == ClassificationType.REPEATABLE_SECTION:
            name = _safe_ident(fd.field_name if fd else cls.field_name)
            if name:
                _templatize_repeatable_paragraph(para, name)
        elif is_dynamic(cls.classification):
            name = _safe_ident(fd.field_name if fd else cls.field_name)
            if name:
                _templatize_paragraph(
                    para, cls.static_prefix or "", f"{{{{ {name} }}}}", cls.static_suffix or ""
                )
            elif (fd and fd.field_name) or cls.field_name:
                logger.warning(
                    "skipping field with unsafe name %r (left as fixed text)",
                    (fd.field_name if fd else cls.field_name),
                )

        if include_name:
            _wrap_optional(para, include_name)

    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()


def build_template_from_examples(
    example_paths: list[str],
) -> tuple[bytes, DocumentExtraction, ClassificationResult, list[FieldDefinition]]:
    """Convenience: full analyze + build directly from example file paths.

    Returns (template_docx_bytes, representative_extraction, classification, fields).
    Useful for tests, the CLI, and seed data.
    """
    extractions = [build_extraction(p, f"ex-{i}") for i, p in enumerate(example_paths)]
    diff = diff_documents(extractions) if len(extractions) >= 2 else None
    rep_i = pick_representative(extractions) if len(extractions) >= 2 else 0
    rep = extractions[rep_i]
    result = classify(rep, diff)
    fields = derive_field_definitions(rep, result)
    template_bytes = build_template_docx(str(example_paths[rep_i]), result, fields)
    return template_bytes, rep, result, fields
