"""Phase-2 generation agent: the compose step refines values + drafts missing ones."""

from __future__ import annotations

from docforge.ai.prompts import LLMComposedValue, LLMComposeResponse
from docforge.ai_router.compose import compose_values
from docforge.schemas.enums import FieldType
from docforge.schemas.routing import PlacementInstruction, RoutingResult
from docforge.schemas.template import FieldDefinition


class _ComposeClient:
    model = "mock"
    active = True
    provider = "openai"

    def __init__(self, resp):
        self._resp = resp

    def complete_agentic(self, *, schema, **kw):
        return self._resp

    def for_tier(self, tier):
        return self


def _fields():
    return [
        FieldDefinition(field_name="title", label="Title", field_type=FieldType.TEXT, required=True),
        FieldDefinition(field_name="amount", label="Amount", field_type=FieldType.NUMBER, required=True),
    ]


def test_compose_refines_value_and_drafts_missing():
    routing = RoutingResult(
        template_id="t", version=1,
        placements=[PlacementInstruction(field_name="title", value="hello world", confidence=0.7)],
        missing_required=["amount"], source="llm",
    )
    resp = LLMComposeResponse(
        values=[
            LLMComposedValue(field_name="title", value="Hello World", confidence=0.95),
            LLMComposedValue(field_name="amount", value="5000", confidence=0.5, ai_drafted=True),
        ]
    )
    out = compose_values(
        routing, _fields(), source_text="hello world; amount five thousand",
        client=_ComposeClient(resp),
    )
    vals = {p.field_name: p for p in out.placements}
    assert vals["title"].value == "Hello World"
    assert vals["amount"].value == "5000" and vals["amount"].ai_drafted is True
    assert out.missing_required == []  # drafted -> no longer missing
    assert out.source == "llm"  # composition preserves the routing source


def test_compose_ignores_unknown_fields_and_empties():
    routing = RoutingResult(template_id="t", version=1, placements=[], missing_required=["title", "amount"], source="llm")
    resp = LLMComposeResponse(
        values=[
            LLMComposedValue(field_name="bogus", value="x"),  # not a real field -> dropped
            LLMComposedValue(field_name="title", value=""),    # empty -> ignored
            LLMComposedValue(field_name="amount", value="42", ai_drafted=True),
        ]
    )
    out = compose_values(routing, _fields(), client=_ComposeClient(resp))
    names = {p.field_name for p in out.placements}
    assert names == {"amount"}
    assert set(out.missing_required) == {"title"}


def test_compose_noop_when_inactive():
    routing = RoutingResult(template_id="t", version=1, placements=[], source="heuristic")

    class _Off:
        active = False

    assert compose_values(routing, _fields(), client=_Off()) is routing
