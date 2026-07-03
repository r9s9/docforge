"""Tags-only mode: every text element becomes a field; the built template
contains only placeholders (no original prose)."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from docforge.ai_classifier import classify, derive_field_definitions
from docforge.ai_classifier.tags_only import enforce_tags_only
from docforge.assembler import assemble
from docforge.schemas.enums import ClassificationType, ElementType, FieldType, needs_field
from docforge.structure_normalizer import build_extraction
from docforge.template_builder import build_template_docx


def _make_doc(tmp_path):
    doc = Document()
    doc.add_heading("Agenda & Topics", level=1)
    doc.add_paragraph("First we discuss the overall goals of the training session.")
    doc.add_paragraph("Then we walk through the hands-on exercises together in pairs.")
    doc.add_paragraph("Finally we collect feedback from every participant.")
    doc.add_heading("Logistics", level=1)
    doc.add_paragraph("Duration: 90 minutes")
    t = doc.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text = "Item"
    t.rows[0].cells[1].text = "Owner"
    t.rows[1].cells[0].text = "Projector"
    t.rows[1].cells[1].text = "Alice"
    path = tmp_path / "training.docx"
    doc.save(str(path))
    return str(path)


def test_enforce_tags_only_fields_everything(tmp_path):
    path = _make_doc(tmp_path)
    ext = build_extraction(path, "d0")
    result = classify(ext, None, mode="tags_only")  # heuristic engine (AI off)

    cls_by_node = {c.node_id: c for c in result.classifications}
    for e in ext.top_level_elements():
        if not (e.text or "").strip() and e.type != ElementType.TABLE:
            continue
        c = cls_by_node[e.node_id]
        if c.classification == ClassificationType.AUTO_FIELD:
            continue
        assert needs_field(c.classification), f"{e.type}: {e.text[:40]!r} stayed {c.classification}"
        assert c.field_name, f"node {e.node_id} has no field name"
        assert c.static_prefix in (None, "")
        assert c.static_suffix in (None, "")
        assert (c.description or "").strip()

    # Headings become their own text fields.
    heading = next(e for e in ext.top_level_elements() if e.type == ElementType.HEADING)
    assert cls_by_node[heading.node_id].classification == ClassificationType.DYNAMIC_TEXT

    # Consecutive body paragraphs collapse into ONE shared repeatable section.
    body = [
        e for e in ext.top_level_elements()
        if e.type == ElementType.PARAGRAPH and "we " in e.text.lower()
    ]
    names = {cls_by_node[e.node_id].field_name for e in body}
    assert len(names) == 1
    assert all(
        cls_by_node[e.node_id].classification == ClassificationType.REPEATABLE_SECTION
        for e in body
    )

    # Table is repeatable.
    table = next(e for e in ext.top_level_elements() if e.type == ElementType.TABLE)
    assert cls_by_node[table.node_id].classification == ClassificationType.REPEATABLE_TABLE

    # Field names unique per field (grouped nodes intentionally share one).
    fields = derive_field_definitions(ext, result)
    field_names = [f.field_name for f in fields]
    assert len(field_names) == len(set(field_names))
    grouped = next(f for f in fields if f.field_name in names)
    assert len(grouped.node_ids) == len(body)  # merged into one multi-node field


def test_tags_only_template_contains_no_original_text(tmp_path):
    path = _make_doc(tmp_path)
    ext = build_extraction(path, "d0")
    result = classify(ext, None, mode="tags_only")
    fields = derive_field_definitions(ext, result)

    template_bytes = build_template_docx(path, result, fields)
    tpl_texts = "\n".join(p.text for p in Document(BytesIO(template_bytes)).paragraphs)

    # No original prose survives — only tags.
    for phrase in ("Agenda & Topics", "overall goals", "hands-on exercises", "90 minutes"):
        assert phrase not in tpl_texts, f"original text {phrase!r} leaked into the template"
    assert "{{" in tpl_texts  # placeholders present
    assert tpl_texts.count("{%p for") == 1  # one loop for the grouped body run

    # Generation renders 100% new text.
    ctx: dict = {}
    for f in fields:
        if f.field_type == FieldType.TABLE:
            ctx[f.field_name] = [{c.field_name: "NEWCELL" for c in f.columns}]
        elif f.classification == ClassificationType.REPEATABLE_SECTION:
            ctx[f.field_name] = ["NEWPARA1", "NEWPARA2"]
        else:
            ctx[f.field_name] = "NEWVALUE"
    out = assemble(template_bytes, ctx, fields)
    out_text = "\n".join(p.text for p in Document(BytesIO(out)).paragraphs)
    assert "NEWVALUE" in out_text and "NEWPARA1" in out_text and "NEWPARA2" in out_text
    assert "overall goals" not in out_text


def test_enforce_tags_only_respects_ai_named_fields(tmp_path):
    path = _make_doc(tmp_path)
    ext = build_extraction(path, "d0")
    # Simulate the AI having named a paragraph already (with a stray prefix).
    result = classify(ext, None)  # smart mode first
    body = next(
        e for e in ext.top_level_elements()
        if e.type == ElementType.PARAGRAPH and "overall goals" in e.text
    )
    c = next(c for c in result.classifications if c.node_id == body.node_id)
    c.classification = ClassificationType.DYNAMIC_TEXT
    c.field_name = "session_goals"
    c.field_type = FieldType.MULTILINE_TEXT
    c.static_prefix = "First "
    enforce_tags_only(ext, result)
    assert c.field_name == "session_goals"  # AI name kept
    assert c.static_prefix is None  # no literal text survives
