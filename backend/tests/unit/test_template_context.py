"""The document-shaped context handed to the generation AI."""

from __future__ import annotations

from docforge.ai.prompts import build_compose_prompt, build_route_prompt
from docforge.ai_router.context import build_template_context, resolve_section_keys
from docforge.schemas.classification import ElementClassification, SectionUnderstanding
from docforge.schemas.enums import ClassificationType, ElementType, FieldType
from docforge.schemas.extraction import DocumentExtraction, NormalizedElement
from docforge.schemas.template import FieldDefinition


def _sections() -> list[SectionUnderstanding]:
    return [
        SectionUnderstanding(
            section_key="summary",
            title="Executive Summary",
            purpose="Orient the reader in a few sentences.",
            expected_content="Two or three paragraphs of plain prose.",
            field_names=["overview"],
        ),
        SectionUnderstanding(
            section_key="risks",
            title="Key Risks",
            purpose="List what could go wrong.",
            expected_content="Bulleted risks with owners.",
            field_names=["risk_list"],
        ),
    ]


def _fields(**overrides) -> list[FieldDefinition]:
    made = [
        FieldDefinition(field_name="overview", label="Overview", field_type=FieldType.MULTILINE_TEXT),
        FieldDefinition(field_name="risk_list", label="Risks", field_type=FieldType.MULTILINE_TEXT),
    ]
    for f in made:
        for k, v in overrides.items():
            setattr(f, k, v)
    return made


def _representative() -> DocumentExtraction:
    return DocumentExtraction(
        document_id="rep",
        filename="rep.docx",
        elements=[
            NormalizedElement(node_id="n1", xpath="/1", type=ElementType.HEADING, text="Executive Summary"),
            NormalizedElement(node_id="n2", xpath="/2", type=ElementType.PARAGRAPH, text="…"),
            NormalizedElement(node_id="n3", xpath="/3", type=ElementType.HEADING, text="Key Risks"),
            NormalizedElement(node_id="n4", xpath="/4", type=ElementType.PARAGRAPH, text="…"),
        ],
    )


# --- section linkage --------------------------------------------------------


def test_resolve_section_keys_matches_on_the_slug_not_the_raw_name():
    fields = _fields()
    sections = [
        SectionUnderstanding(section_key="summary", field_names=["Overview"]),
        SectionUnderstanding(section_key="risks", field_names=["Risk List"]),
    ]
    resolve_section_keys(fields, sections)
    assert [f.section_key for f in fields] == ["summary", "risks"]


def test_resolve_section_keys_falls_back_to_a_close_name():
    fields = _fields()
    sections = [SectionUnderstanding(section_key="summary", field_names=["overviews"])]
    resolve_section_keys(fields, sections)
    assert fields[0].section_key == "summary"


def test_unclaimed_fields_join_the_preceding_section():
    # Fields are in document order, so a field the model forgot to list almost
    # always belongs with the one before it.
    fields = _fields()
    sections = [SectionUnderstanding(section_key="summary", field_names=["overview"])]
    resolve_section_keys(fields, sections)
    assert fields[1].section_key == "summary"


def test_existing_section_keys_are_never_overwritten():
    fields = _fields()
    fields[0].section_key = "already_set"
    resolve_section_keys(fields, _sections())
    assert fields[0].section_key == "already_set"


# --- context assembly -------------------------------------------------------


def test_context_carries_document_type_sections_and_places():
    context = build_template_context(
        document_type="project report",
        sections=_sections(),
        classifications=[
            ElementClassification(
                node_id="n2",
                classification=ClassificationType.DYNAMIC_TEXT,
                field_name="overview",
                static_prefix="Summary: ",
            )
        ],
        fields=_fields(),
        representative=_representative(),
    )
    assert context["document_type"] == "project report"
    assert [s["section_key"] for s in context["sections"]] == ["summary", "risks"]
    assert context["sections"][0]["purpose"].startswith("Orient the reader")
    assert context["field_places"]["overview"]["label_before"] == "Summary: "


def test_field_places_record_the_heading_each_field_sits_under():
    fields = _fields()
    fields[0].node_ids = ["n2"]
    fields[1].node_ids = ["n4"]
    context = build_template_context(
        sections=_sections(), fields=fields, representative=_representative()
    )
    places = context["field_places"]
    assert places["overview"]["under_heading"] == "Executive Summary"
    assert places["risk_list"]["under_heading"] == "Key Risks"
    assert places["overview"]["order"] < places["risk_list"]["order"]


def test_context_is_empty_without_fields():
    assert build_template_context(document_type="invoice", fields=[]) == {}


def test_context_survives_a_template_with_no_section_understanding():
    context = build_template_context(document_type="invoice", fields=_fields())
    assert context["document_type"] == "invoice"
    assert "sections" not in context


# --- prompt wiring ----------------------------------------------------------


def test_route_prompt_describes_the_document_when_context_is_supplied():
    context = build_template_context(
        document_type="project report", sections=_sections(), fields=_fields()
    )
    _system, _developer, user = build_route_prompt(
        _fields(), raw_text="notes", template_context=context
    )
    assert "The document you are filling in is: project report." in user
    assert "Executive Summary" in user
    assert "Orient the reader" in user


def test_prompts_are_unchanged_without_context():
    fields = _fields()
    plain = build_route_prompt(fields, raw_text="notes")[2]
    assert "organised into these sections" not in plain
    composed = build_compose_prompt(fields, [], source_text="notes")[2]
    assert "organised into these sections" not in composed


def test_compose_prompt_includes_where_each_field_sits():
    fields = _fields()
    fields[0].node_ids = ["n2"]
    context = build_template_context(
        sections=_sections(), fields=fields, representative=_representative()
    )
    _system, _developer, user = build_compose_prompt(
        fields, [], source_text="notes", template_context=context
    )
    assert "under_heading" in user and "Executive Summary" in user
