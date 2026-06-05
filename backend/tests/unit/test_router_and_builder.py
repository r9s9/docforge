"""Unit tests for content routing and template build+assemble."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from docforge.ai_router import route_structured, route_unstructured_heuristic
from docforge.assembler import assemble
from docforge.schemas.enums import FieldType
from docforge.schemas.template import FieldDefinition
from docforge.template_builder import build_template_from_examples


def _fields():
    return [
        FieldDefinition(field_name="project_name", label="Project Name", field_type=FieldType.TEXT, required=True),
        FieldDefinition(field_name="report_date", label="Report Date", field_type=FieldType.DATE, required=True),
        FieldDefinition(field_name="summary", label="Summary", field_type=FieldType.MULTILINE_TEXT, required=False),
    ]


def test_route_structured_reports_missing_required():
    res = route_structured(_fields(), {"project_name": "X"}, "t", 1)
    assert "report_date" in res.missing_required
    assert {p.field_name for p in res.placements} == {"project_name"}


def test_route_unstructured_matches_labels_and_prose():
    text = "Project Name: Orion\nReport Date: 2026-07-01\nWe finished the pilot successfully."
    res = route_unstructured_heuristic(_fields(), text, "t", 1)
    by = {p.field_name: p.value for p in res.placements}
    assert by["project_name"] == "Orion"
    assert by["report_date"] == "2026-07-01"
    assert "summary" in by  # leftover prose routed to the free-text field


def test_build_then_assemble_roundtrip(project_docs):
    template_bytes, _, _, fields = build_template_from_examples([str(p) for p in project_docs])
    context = {
        "project_name": "Orion",
        "report_date": "2026-07-01",
        "prepared_by": "Alice Brown",
        "summary": "On track.",
        "task_status": [
            {"task": "Design", "owner": "M. Lee", "status": "Done", "due_date": "2026-07-01"},
        ],
    }
    out = assemble(template_bytes, context, fields)
    doc = Document(BytesIO(out))
    texts = [p.text for p in doc.paragraphs]
    assert "Project Name: Orion" in texts
    assert "Report Date: 2026-07-01" in texts
    # header + exactly one rendered data row
    assert len(doc.tables[0].rows) == 2
