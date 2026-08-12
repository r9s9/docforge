"""The document writer: one pass that writes every field together."""

from __future__ import annotations

import pytest

from docforge.ai.client import LLMError
from docforge.ai.prompts import (
    LLMSectionSkip,
    LLMWrittenPlacement,
    LLMWriteResponse,
    build_writer_prompt,
)
from docforge.ai.tools import writer_tools
from docforge.ai_router.writer import MAX_WRITER_FIELDS, try_write_document, write_document
from docforge.schemas.enums import ElementType, FieldType
from docforge.schemas.extraction import DocumentExtraction, NormalizedElement
from docforge.schemas.template import FieldDefinition


class _WriterClient:
    model = "mock"
    active = True
    provider = "openai"

    class config:  # noqa: D106 - stands in for AIConfig
        model = "mock"

        @staticmethod
        def model_for_tier(tier):
            return "mock-reasoning"

    def __init__(self, response=None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.tools_seen: list = []

    def complete_agentic(self, *, schema, tools=None, **kw):
        if self._error:
            raise self._error
        self.tools_seen = tools or []
        return self._response

    def for_tier(self, tier):
        return self


def _fields() -> list[FieldDefinition]:
    return [
        FieldDefinition(
            field_name="overview", label="Overview",
            field_type=FieldType.MULTILINE_TEXT, required=False,
        ),
        FieldDefinition(field_name="amount", label="Amount", field_type=FieldType.NUMBER, required=True),
        FieldDefinition(field_name="signed_on", label="Signed", field_type=FieldType.DATE, required=False),
    ]


def _write(response, fields=None, **kw):
    return write_document(
        fields if fields is not None else _fields(),
        client=_WriterClient(response),
        template_id="t",
        version=1,
        **kw,
    )


def test_writer_maps_a_response_into_a_routing_result():
    out = _write(
        LLMWriteResponse(
            placements=[
                LLMWrittenPlacement(field_name="overview", value="Two paragraphs.\n\nHere.", confidence=0.9),
                LLMWrittenPlacement(field_name="amount", value="5000", confidence=0.6, ai_drafted=True),
            ]
        )
    )
    values = {p.field_name: p for p in out.placements}
    assert out.source == "writer"
    assert values["overview"].value.startswith("Two paragraphs.")
    assert values["amount"].ai_drafted is True and values["amount"].note == "AI-drafted"
    assert out.missing_required == []
    assert out.model_used == "mock-reasoning"


def test_writer_records_sections_it_deliberately_skipped():
    out = _write(
        LLMWriteResponse(
            placements=[LLMWrittenPlacement(field_name="amount", value="10")],
            skipped_sections=[LLMSectionSkip(section_key="risks", reason="nothing in the source")],
        )
    )
    assert out.skipped_sections == [{"section_key": "risks", "reason": "nothing in the source"}]


def test_writer_drops_invented_fields_duplicates_and_empties():
    out = _write(
        LLMWriteResponse(
            placements=[
                LLMWrittenPlacement(field_name="not_a_field", value="x"),
                LLMWrittenPlacement(field_name="overview", value="first wins"),
                LLMWrittenPlacement(field_name="overview", value="second ignored"),
                LLMWrittenPlacement(field_name="signed_on", value=""),
            ]
        )
    )
    assert [p.field_name for p in out.placements] == ["overview"]
    assert out.placements[0].value == "first wins"


def test_a_value_failing_its_type_is_flagged_for_review():
    # The model rates its own confidence; only an independent check catches a
    # confidently-wrong number.
    out = _write(
        LLMWriteResponse(
            placements=[LLMWrittenPlacement(field_name="amount", value="not a number", confidence=0.99)]
        )
    )
    placement = out.placements[0]
    assert placement.confidence <= 0.3
    assert "Needs review" in placement.note


def test_required_fields_left_unwritten_are_reported_missing():
    out = _write(LLMWriteResponse(placements=[]))
    assert out.missing_required == ["amount"]


# --- fallback behaviour -----------------------------------------------------


def test_try_write_returns_none_on_failure_so_the_caller_falls_back():
    result = try_write_document(
        _fields(),
        client=_WriterClient(error=LLMError("model exploded")),
        template_id="t",
        version=1,
    )
    assert result is None


def test_cancellation_is_not_swallowed_as_a_fallback():
    from docforge.ai.client import LLMCancelled

    with pytest.raises(LLMCancelled):
        try_write_document(
            _fields(),
            client=_WriterClient(error=LLMCancelled()),
            template_id="t",
            version=1,
        )


def test_writer_is_skipped_for_templates_too_large_for_one_response():
    many = [
        FieldDefinition(field_name=f"f{i}", label=f"F{i}", field_type=FieldType.TEXT)
        for i in range(MAX_WRITER_FIELDS + 1)
    ]
    assert try_write_document(many, client=_WriterClient(LLMWriteResponse()), template_id="t", version=1) is None


def test_writer_can_be_turned_off(monkeypatch):
    from docforge import config

    settings = config.get_settings()
    monkeypatch.setattr(settings, "ai_writer_enabled", False)
    assert try_write_document(
        _fields(), client=_WriterClient(LLMWriteResponse()), template_id="t", version=1
    ) is None


# --- tools ------------------------------------------------------------------


def _source_doc() -> DocumentExtraction:
    long_text = "detail " * 300
    return DocumentExtraction(
        document_id="d",
        filename="d.docx",
        elements=[
            NormalizedElement(node_id="n1", xpath="/", type=ElementType.HEADING, text="Background"),
            NormalizedElement(node_id="n2", xpath="/", type=ElementType.PARAGRAPH, text=long_text),
        ],
    )


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


def test_get_section_context_answers_what_a_section_is_for():
    context = {
        "sections": [
            {"section_key": "summary", "title": "Summary", "purpose": "Orient the reader", "fields": ["overview"]},
            {"section_key": "risks", "title": "Risks", "purpose": "List problems", "fields": []},
        ]
    }
    tools = writer_tools(_fields(), context)
    out = _tool(tools, "get_section_context").run({"section_key": "summary"})
    assert out["purpose"] == "Orient the reader"
    assert out["other_sections"] == ["risks"]
    assert "error" in _tool(tools, "get_section_context").run({"section_key": "nope"})


def test_get_source_block_recovers_text_the_outline_truncated():
    tools = writer_tools(_fields(), {}, _source_doc())
    out = _tool(tools, "get_source_block").run({"block_id": "b1"})
    assert out["text"].startswith("detail detail")
    assert "error" in _tool(tools, "get_source_block").run({"block_id": "b99"})


def test_source_block_tool_is_honest_when_there_is_no_document():
    tools = writer_tools(_fields(), {})
    assert "error" in _tool(tools, "get_source_block").run({"block_id": "b1"})


def test_writer_prompt_stands_alone_without_tools():
    # Providers without tool support degrade to a single call, so everything the
    # writer needs has to be in the message itself.
    _system, _developer, user = build_writer_prompt(
        _fields(),
        template_context={"document_type": "report", "sections": [{"section_key": "s", "title": "S", "purpose": "P", "fields": []}]},
        source_outline="# Background\nSome text.",
    )
    assert "report" in user and "Background" in user and "overview" in user


def test_writer_output_counts_as_a_real_ai_call():
    # Free-tier accounting and the audit trail key off this: a writer run is a
    # model call and must be charged like one, unlike deterministic mapping.
    from docforge.schemas.routing import RoutingResult

    assert _write(LLMWriteResponse(placements=[])).used_ai is True
    assert RoutingResult(template_id="t", version=1, source="structural").used_ai is False
    assert RoutingResult(template_id="t", version=1, source="heuristic").used_ai is False


def test_writer_prompt_carries_review_findings_when_revising():
    _system, _developer, user = build_writer_prompt(
        _fields(),
        review_findings=[{"kind": "duplicate", "message": "summary repeats the body"}],
        prior_values={"overview": "a draft"},
    )
    assert "summary repeats the body" in user
    assert "a draft" in user
