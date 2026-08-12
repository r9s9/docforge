"""Reading the assembled document back for problems per-field checks can't see."""

from __future__ import annotations

from docforge.ai.client import LLMError
from docforge.ai.prompts import LLMRenderFinding, LLMRenderReview, build_render_review_prompt
from docforge.ai_router.verify import has_correctable, review_rendered_output
from docforge.schemas.routing import PlacementInstruction, RoutingResult


class _ReviewClient:
    model = "mock"
    active = True
    provider = "openai"

    def __init__(self, response=None, error: Exception | None = None, active: bool = True):
        self._response = response
        self._error = error
        self.active = active

    def complete_json(self, **kw):
        if self._error:
            raise self._error
        return self._response

    def for_tier(self, tier):
        return self


def _blocks() -> list[dict]:
    return [
        {"type": "heading", "text": "Summary", "style": "Heading 1"},
        {"type": "paragraph", "text": "The pilot went well.", "style": "Normal"},
        {"type": "heading", "text": "Risks", "style": "Heading 1"},
    ]


def _routing(source: str = "writer") -> RoutingResult:
    return RoutingResult(
        template_id="t",
        version=1,
        placements=[PlacementInstruction(field_name="overview", value="The pilot went well.")],
        source=source,
    )


def test_findings_are_returned_for_review():
    response = LLMRenderReview(
        findings=[
            LLMRenderFinding(
                kind="empty_section", section_key="risks",
                message="The Risks section has a heading but no content.", severity="error",
            )
        ]
    )
    findings = review_rendered_output(_blocks(), _routing(), client=_ReviewClient(response))
    assert len(findings) == 1
    assert findings[0]["kind"] == "empty_section"
    assert has_correctable(findings) is True


def test_findings_without_a_message_are_dropped():
    response = LLMRenderReview(
        findings=[LLMRenderFinding(kind="other", message="  "), LLMRenderFinding(message="real one")]
    )
    findings = review_rendered_output(_blocks(), _routing(), client=_ReviewClient(response))
    assert [f["message"] for f in findings] == ["real one"]


def test_a_clean_document_produces_nothing():
    findings = review_rendered_output(
        _blocks(), _routing(), client=_ReviewClient(LLMRenderReview())
    )
    assert findings == []
    assert has_correctable(findings) is False


def test_review_never_breaks_a_generation():
    # Advisory only: a failed review must not stop a document being produced.
    findings = review_rendered_output(
        _blocks(), _routing(), client=_ReviewClient(error=LLMError("boom"))
    )
    assert findings == []


def test_review_is_skipped_without_ai_or_content():
    assert review_rendered_output(_blocks(), _routing(), client=_ReviewClient(active=False)) == []
    assert review_rendered_output([], _routing(), client=_ReviewClient(LLMRenderReview())) == []


def test_only_serious_findings_justify_a_rewrite():
    warnings = [{"severity": "warning", "message": "a bit terse"}]
    assert has_correctable(warnings) is False
    assert has_correctable([*warnings, {"severity": "error", "message": "empty section"}]) is True


def test_prompt_tells_the_reviewer_which_sections_were_skipped_on_purpose():
    routing = _routing()
    routing.skipped_sections = [{"section_key": "risks", "reason": "nothing supplied"}]
    _system, _developer, user = build_render_review_prompt(
        _blocks(), placed_fields=["overview"], skipped_sections=routing.skipped_sections
    )
    assert "do NOT report these as problems" in user
    assert "nothing supplied" in user


def test_review_only_runs_when_a_model_wrote_the_content(monkeypatch):
    from docforge import config
    from docforge.services.generation import review_output

    settings = config.get_settings()
    monkeypatch.setattr(settings, "ai_verify_enabled", True)
    # Deterministic mapping returns exactly what it was given — nothing to check.
    assert review_output(_blocks(), _routing("structural"), settings=settings) == []
    assert review_output(_blocks(), _routing("heuristic"), settings=settings) == []


def test_review_can_be_turned_off(monkeypatch):
    from docforge import config
    from docforge.services.generation import review_output

    settings = config.get_settings()
    monkeypatch.setattr(settings, "ai_verify_enabled", False)
    assert review_output(_blocks(), _routing("writer"), settings=settings) == []
