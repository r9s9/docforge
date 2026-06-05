"""Unit tests for the multi-document diff engine."""

from __future__ import annotations

from docforge.multi_doc_differ import diff_documents
from docforge.schemas.enums import DiffStatus
from docforge.structure_normalizer import build_extraction


def _diff(docs):
    exts = [build_extraction(p, f"d{i}") for i, p in enumerate(docs)]
    return exts, diff_documents(exts)


def _find(res, needle):
    for d in res.node_diffs:
        if any(needle in t for t in d.sample_texts):
            return d
    return None


def test_diff_title_is_identical(project_docs):
    _, res = _diff(project_docs)
    d = _find(res, "MONTHLY PROJECT STATUS REPORT")
    assert d is not None
    assert d.status == DiffStatus.IDENTICAL
    assert d.is_constant


def test_diff_partial_date_keeps_label_static(project_docs):
    _, res = _diff(project_docs)
    d = _find(res, "Report Date")
    assert d is not None
    assert d.status == DiffStatus.PARTIAL_CHANGE
    assert d.static_prefix == "Report Date: "
    assert d.detected_kind == "date"
    # The whole date is the variable token (no hard-coded year fragment).
    assert "2026-05-01" in d.variable_parts


def test_diff_project_name_is_text_not_subsplit(project_docs):
    _, res = _diff(project_docs)
    d = _find(res, "Project Name")
    assert d.status == DiffStatus.PARTIAL_CHANGE
    assert d.static_prefix == "Project Name: "
    assert "Apollo Data Migration" in d.variable_parts


def test_diff_table_row_count_changed(project_docs):
    _, res = _diff(project_docs)
    tables = [d for d in res.node_diffs if d.type.value == "table"]
    assert tables
    t = tables[0]
    assert t.status == DiffStatus.ROW_COUNT_CHANGED
    assert t.header_identical is True
    assert t.row_count_variable is True


def test_diff_invoice_line_items_repeatable(invoice_docs):
    _, res = _diff(invoice_docs)
    tables = [d for d in res.node_diffs if d.type.value == "table"]
    assert tables and tables[0].row_count_variable
