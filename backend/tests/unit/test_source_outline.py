"""Uploaded documents are described to the AI as an outline, not a pool of text."""

from __future__ import annotations

from docforge.ai_router.document import (
    render_content_outline,
    render_content_text,
    source_blocks,
)
from docforge.schemas.enums import ElementType
from docforge.schemas.extraction import (
    DocumentExtraction,
    NormalizedElement,
    NumberingInfo,
    TableStructure,
)


def _doc(*elements: NormalizedElement) -> DocumentExtraction:
    return DocumentExtraction(document_id="d", filename="d.docx", elements=list(elements))


def _para(node_id: str, text: str) -> NormalizedElement:
    return NormalizedElement(node_id=node_id, xpath="/", type=ElementType.PARAGRAPH, text=text)


def _heading(node_id: str, text: str, level: str = "1") -> NormalizedElement:
    return NormalizedElement(
        node_id=node_id, xpath="/", type=ElementType.HEADING, subtype=level, text=text
    )


def _item(node_id: str, text: str, *, ordered: bool = False, level: int = 0) -> NormalizedElement:
    return NormalizedElement(
        node_id=node_id,
        xpath="/",
        type=ElementType.LIST_ITEM,
        subtype="ordered" if ordered else "bullet",
        text=text,
        numbering_info=NumberingInfo(level=level, is_ordered=ordered),
    )


def test_outline_keeps_heading_levels():
    outline = render_content_outline(
        _doc(_heading("n1", "Background"), _para("n2", "Some prose."), _heading("n3", "Detail", "2"))
    )
    assert "# Background" in outline
    assert "## Detail" in outline
    assert "Some prose." in outline


def test_outline_marks_bullets_ordered_items_and_nesting():
    outline = render_content_outline(
        _doc(
            _item("n1", "top bullet"),
            _item("n2", "nested bullet", level=1),
            _item("n3", "first step", ordered=True),
        )
    )
    lines = [ln for ln in outline.splitlines() if ln.strip()]
    assert lines[0] == "- top bullet"
    assert lines[1] == "  - nested bullet"
    assert lines[2] == "1. first step"


def test_outline_renders_tables_with_headers_and_rows():
    table = NormalizedElement(
        node_id="n1",
        xpath="/",
        type=ElementType.TABLE,
        table_structure=TableStructure(
            headers=["Item", "Qty"], rows=[["Item", "Qty"], ["Widget", "2"]]
        ),
    )
    outline = render_content_outline(_doc(table))
    assert "TABLE: Item | Qty" in outline
    assert "  Widget | 2" in outline


def test_long_paragraphs_are_truncated_with_a_recoverable_id():
    long_text = "word " * 400
    outline = render_content_outline(_doc(_para("n1", long_text)), max_para_chars=100)
    assert "[truncated — get_source_block b0]" in outline
    assert len(outline) < 300


def test_source_blocks_return_the_full_text_behind_a_truncation():
    long_text = "word " * 400
    doc = _doc(_heading("n1", "Title"), _para("n2", long_text))
    blocks = source_blocks(doc)
    # Ids line up with the outline's own numbering.
    assert "[truncated — get_source_block b1]" in render_content_outline(doc, max_para_chars=50)
    assert blocks["b1"].startswith("word word")
    assert len(blocks["b1"]) > 1000


def test_outline_preserves_order_that_the_flat_rendering_loses():
    doc = _doc(
        _heading("n1", "Risks"),
        _para("n2", "A risk."),
        _heading("n3", "Plan"),
        _para("n4", "A plan."),
    )
    outline = render_content_outline(doc)
    assert outline.index("# Risks") < outline.index("A risk.") < outline.index("# Plan")
    # The flat rendering keeps the words but drops every structural cue.
    flat = render_content_text({"paragraphs": [e.text for e in doc.elements], "tables": []})
    assert "#" not in flat
