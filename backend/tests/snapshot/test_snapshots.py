"""Snapshot tests — guard the stability of extraction + template intelligence."""

from __future__ import annotations

from docforge.ai_classifier import classify, derive_field_definitions
from docforge.multi_doc_differ import diff_documents
from docforge.structure_normalizer import build_extraction


def test_extraction_body_structure_snapshot(project_docs):
    ext = build_extraction(project_docs[0], "d0")
    body_top = [
        e.type.value
        for e in ext.elements
        if e.parent_node_id is None and e.header_footer_scope is None
    ]
    assert body_top == [
        "paragraph",  # title
        "paragraph",  # Project Name:
        "paragraph",  # Report Date:
        "paragraph",  # Prepared By:
        "paragraph",  # intro
        "heading",  # Summary
        "paragraph",  # summary body
        "heading",  # Task Status
        "table",  # task table
        "heading",  # Confidentiality
        "paragraph",  # confidential text
    ]


def test_project_report_intelligence_snapshot(project_docs):
    exts = [build_extraction(p, f"d{i}") for i, p in enumerate(project_docs)]
    diff = diff_documents(exts)
    result = classify(exts[0], diff)
    fields = derive_field_definitions(exts[0], result)

    snapshot = {
        f.field_name: (f.field_type.value, f.classification.value, f.required) for f in fields
    }
    assert snapshot == {
        "project_name": ("text", "DYNAMIC_TEXT", True),
        "report_date": ("date", "DYNAMIC_DATE", True),
        "prepared_by": ("person", "DYNAMIC_PERSON", True),
        "summary": ("text", "DYNAMIC_TEXT", True),
        "task_status": ("table", "REPEATABLE_TABLE", True),
    }
    assert result.document_type_guess == "Monthly Project Status Report"


def test_invoice_intelligence_snapshot(invoice_docs):
    exts = [build_extraction(p, f"d{i}") for i, p in enumerate(invoice_docs)]
    diff = diff_documents(exts)
    result = classify(exts[0], diff)
    fields = {f.field_name: f.field_type.value for f in derive_field_definitions(exts[0], result)}
    # Labels -> field names; line-items table detected as repeatable.
    assert fields.get("invoice_number") == "text"
    assert fields.get("invoice_date") == "date"
    assert fields.get("line_items") == "table"
