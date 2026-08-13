"""A correct response must not be discarded over the spelling of a field name."""

from __future__ import annotations

from docforge.ai.prompts import LLMWrittenPlacement, LLMWriteResponse
from docforge.ai_router.naming import build_name_resolver
from docforge.schemas.enums import FieldType
from docforge.schemas.template import FieldDefinition
from tests.unit.test_writer_agent import _WriterClient  # shared mock client

from docforge.ai_router.writer import write_document


def _fields() -> list[FieldDefinition]:
    return [
        FieldDefinition(
            field_name="header_level_1_title", label="Header Level 1",
            field_type=FieldType.TEXT, required=False,
        ),
        FieldDefinition(
            field_name="body_body", label="Body Body",
            field_type=FieldType.MULTILINE_TEXT, required=False,
        ),
        FieldDefinition(
            field_name="review_scope", label="Review Scope",
            field_type=FieldType.TEXT, required=False,
        ),
    ]


def test_an_exact_name_still_wins():
    resolve = build_name_resolver(_fields())
    assert resolve("body_body") == "body_body"


def test_a_dropped_suffix_is_recognised():
    resolve = build_name_resolver(_fields())
    assert resolve("header_level_1") == "header_level_1_title"


def test_the_label_resolves_to_its_field():
    resolve = build_name_resolver(_fields())
    assert resolve("Header Level 1") == "header_level_1_title"
    assert resolve("Review Scope") == "review_scope"


def test_an_unrelated_name_is_refused_not_guessed():
    # Placing content in the wrong section is worse than leaving it out.
    resolve = build_name_resolver(_fields())
    assert resolve("executive_summary") is None
    assert resolve("") is None
    assert resolve(None) is None


def test_similar_but_distinct_fields_never_merge():
    fields = [
        FieldDefinition(field_name="review_scope", label="Scope"),
        FieldDefinition(field_name="review_summary", label="Summary"),
    ]
    resolve = build_name_resolver(fields)
    assert resolve("review_scope") == "review_scope"
    assert resolve("review_summary") == "review_summary"


def test_near_miss_names_are_placed_instead_of_dropped():
    response = LLMWriteResponse(
        placements=[
            LLMWrittenPlacement(field_name="header_level_1", value="Executive Summary"),
            LLMWrittenPlacement(field_name="Body Body", value="The pilot went well."),
        ]
    )
    out = write_document(
        _fields(), client=_WriterClient(response), template_id="t", version=1
    )
    placed = {p.field_name: p.value for p in out.placements}
    assert placed["header_level_1_title"] == "Executive Summary"
    assert placed["body_body"] == "The pilot went well."


def test_content_for_a_field_that_does_not_exist_is_reported():
    """Silence here is how a document ends up empty with nothing to explain it."""
    response = LLMWriteResponse(
        placements=[LLMWrittenPlacement(field_name="quarterly_revenue", value="12m")]
    )
    out = write_document(
        _fields(), client=_WriterClient(response), template_id="t", version=1
    )
    assert out.placements == []
    assert any("quarterly_revenue" in line for line in out.unmapped_content)
