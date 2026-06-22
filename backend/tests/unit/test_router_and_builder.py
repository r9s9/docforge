"""Unit tests for content routing and template build+assemble."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from docforge.ai_router import route_structured, route_unstructured_heuristic
from docforge.assembler import assemble
from docforge.schemas.enums import FieldType
from docforge.schemas.template import FieldDefinition
from docforge.template_builder import build_template_from_examples
from docforge.template_builder.builder import (
    _neutralize_run,
    _neutralize_stray_tags,
    _run_has_image,
    _templatize_paragraph,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


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


def test_templatize_paragraph_preserves_images():
    # A paragraph that holds a logo + dynamic text: templatizing the text must
    # insert the {{ placeholder }} WITHOUT deleting the image run (regression:
    # logos used to vanish from the built template and every generated document).
    doc = Document()
    para = doc.add_paragraph("Logo: ")
    img_run = para.add_run()
    img_run._element.append(OxmlElement("w:drawing"))  # stand-in for an embedded picture
    assert _run_has_image(img_run)

    _templatize_paragraph(para, "Logo: ", "{{ company_logo }}", "")

    # Image drawing survived, and the placeholder text is present.
    assert para._p.findall(".//" + qn("w:drawing"))
    assert "{{ company_logo }}" in para.text


def test_neutralize_run_disarms_literal_jinja():
    # A run that already contains "{{ Client }}" must no longer read as a tag,
    # but must stay visually identical (only a zero-width space is inserted).
    out = _neutralize_run("Dear {{ Client }}, see {% if x %}note{% endif %}.")
    assert "{{" not in out and "}}" not in out
    assert "{%" not in out and "%}" not in out
    assert out.replace("​", "") == "Dear {{ Client }}, see {% if x %}note{% endif %}."


def test_build_assemble_ignores_stray_template_markers():
    # Simulate an uploaded example that is itself an ILF-style template carrying
    # its own literal "{{ ... }}" markers. The build must neutralize them so
    # docxtpl renders without a TemplateSyntaxError.
    src = Document()
    src.add_paragraph("Header: {{1Headers3}} and {% weird %} text")
    _neutralize_stray_tags(src)
    bio = BytesIO()
    src.save(bio)
    # The saved doc, treated as a template, renders cleanly with an empty context.
    out = assemble(bio.getvalue(), {}, [])
    rendered = Document(BytesIO(out))
    text = "\n".join(p.text for p in rendered.paragraphs)
    # Original markers survive visually (sans the invisible zero-width space).
    assert "{{1Headers3}}" in text.replace("​", "")
