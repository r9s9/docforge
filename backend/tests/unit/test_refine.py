"""Refine: changing the draft by asking for it in words."""

from __future__ import annotations

import pytest

from docforge.ai.prompts import LLMComposedValue, LLMRefineResponse, build_refine_prompt
from docforge.schemas.enums import FieldType
from docforge.schemas.template import FieldDefinition


class _RefineClient:
    model = "mock-reasoning"
    provider = "openai"

    def __init__(self, response=None, active: bool = True):
        self._response = response
        self.active = active

    def complete_json(self, **kw):
        return self._response

    def for_tier(self, tier):
        return self


class _Registry:
    def __init__(self, fields):
        self._fields = fields

    def load_fields(self, template_id, version):
        return self._fields

    def load_intelligence(self, template_id, version):
        raise FileNotFoundError  # a bare template: refine still works

    def load_representative(self, template_id, version):
        return None


class _Template:
    id = "tpl"
    latest_version = 1
    document_type = "report"


def _fields() -> list[FieldDefinition]:
    return [
        FieldDefinition(field_name="summary", label="Summary", field_type=FieldType.MULTILINE_TEXT),
        FieldDefinition(field_name="amount", label="Amount", field_type=FieldType.NUMBER),
        FieldDefinition(field_name="notes", label="Notes", field_type=FieldType.TEXT, required=False),
    ]


def _refine(response, values=None, monkeypatch=None, **kw):
    from docforge.services import refine as refine_module

    fields = _fields()
    if monkeypatch is not None:
        monkeypatch.setattr(refine_module, "LLMClient", lambda cfg: _RefineClient(response))
    return refine_module.refine_values(
        db=None,
        template=_Template(),
        version=1,
        messages=[{"role": "user", "content": "shorten the summary"}],
        current_values=values or {"summary": "A long draft.", "amount": "500"},
        registry=_Registry(fields),
        **kw,
    )


def test_only_changed_fields_come_back(monkeypatch):
    response = LLMRefineResponse(
        reply="Cut the summary to one sentence.",
        updates=[LLMComposedValue(field_name="summary", value="Short now.", confidence=0.9)],
    )
    out = _refine(response, monkeypatch=monkeypatch)
    assert out["reply"] == "Cut the summary to one sentence."
    assert [u["field_name"] for u in out["updates"]] == ["summary"]
    assert out["updates"][0]["value"] == "Short now."


def test_invented_fields_and_empty_values_are_dropped(monkeypatch):
    response = LLMRefineResponse(
        updates=[
            LLMComposedValue(field_name="not_a_field", value="x"),
            LLMComposedValue(field_name="summary", value=""),
            LLMComposedValue(field_name="amount", value="750"),
        ],
        removed=["notes", "also_not_a_field"],
    )
    out = _refine(response, monkeypatch=monkeypatch)
    assert [u["field_name"] for u in out["updates"]] == ["amount"]
    assert out["removed"] == ["notes"]


def test_a_value_failing_its_type_is_flagged_not_silently_applied(monkeypatch):
    response = LLMRefineResponse(
        updates=[LLMComposedValue(field_name="amount", value="quite a lot", confidence=0.95)]
    )
    out = _refine(response, monkeypatch=monkeypatch)
    update = out["updates"][0]
    assert update["confidence"] <= 0.3
    assert "Needs review" in update["note"]


def test_refine_says_so_when_no_ai_is_connected(monkeypatch):
    from docforge.services import refine as refine_module

    monkeypatch.setattr(
        refine_module, "LLMClient", lambda cfg: _RefineClient(None, active=False)
    )
    with pytest.raises(refine_module.RefineUnavailable):
        refine_module.refine_values(
            db=None,
            template=_Template(),
            version=1,
            messages=[{"role": "user", "content": "shorten it"}],
            current_values={},
            registry=_Registry(_fields()),
        )


def test_section_skips_pass_through(monkeypatch):
    response = LLMRefineResponse(reply="Dropped the risks section.", skip_sections=["risks"])
    out = _refine(response, monkeypatch=monkeypatch)
    assert out["skip_sections"] == ["risks"]


# --- prompt -----------------------------------------------------------------


def test_prompt_carries_the_draft_and_the_conversation():
    _system, _developer, user = build_refine_prompt(
        _fields(),
        [
            {"role": "user", "content": "shorten the summary"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "now make it formal"},
        ],
        {"summary": "The current text."},
    )
    assert "The current text." in user
    assert "now make it formal" in user
    assert "shorten the summary" in user  # earlier turns give the edit its context


def test_prompt_insists_on_a_patch_not_a_whole_document():
    _system, developer, _user = build_refine_prompt(_fields(), [], {})
    assert "ONLY fields you are changing" in developer
    assert "an unchanged field echoed back is a bug" in developer


def test_prompt_includes_the_source_so_edits_stay_faithful():
    _system, _developer, user = build_refine_prompt(
        _fields(), [], {}, source_context="The pilot ran for six weeks."
    )
    assert "The pilot ran for six weeks." in user
