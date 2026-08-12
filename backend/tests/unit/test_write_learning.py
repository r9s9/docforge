"""Learning from how the user edits what the AI wrote."""

from __future__ import annotations

from docforge.schemas.routing import PlacementInstruction
from docforge.services.learning import diff_placements


def _prior(**values) -> list[PlacementInstruction]:
    return [PlacementInstruction(field_name=k, value=v) for k, v in values.items()]


def test_no_edits_means_nothing_to_learn():
    prior = _prior(summary="Unchanged text.")
    assert diff_placements(prior, {"summary": "Unchanged text."}) == []


def test_a_cleared_field_says_the_ai_should_not_have_filled_it():
    summaries = diff_placements(_prior(notes="Some filler."), {"notes": ""})
    assert summaries == ['the user cleared "notes" — the AI should not have filled it']


def test_a_field_filled_by_hand_says_the_ai_left_it_empty():
    summaries = diff_placements(_prior(owner=""), {"owner": "R. Sadeghi"})
    assert "filled" in summaries[0] and "owner" in summaries[0]


def test_a_heavily_cut_value_teaches_brevity():
    summaries = diff_placements(
        _prior(summary="one two three four five six seven eight nine ten"),
        {"summary": "one two"},
    )
    assert "more briefly" in summaries[0]


def test_an_expanded_value_teaches_more_detail():
    summaries = diff_placements(
        _prior(summary="short"), {"summary": "a considerably longer replacement value here"}
    )
    assert "more detail" in summaries[0]


def test_restructuring_into_paragraphs_is_recognised():
    summaries = diff_placements(
        _prior(body="one line of roughly this length here"),
        {"body": "one line of roughly\n\nthis length here"},
    )
    assert "paragraphs or bullets" in summaries[0]


def test_a_rewrite_keeps_only_a_short_excerpt_not_the_whole_value():
    long_value = "x" * 400
    summaries = diff_placements(_prior(summary="y" * 380), {"summary": long_value})
    assert len(summaries[0]) < 200  # the shape of the edit, not its content


def test_non_text_values_are_skipped():
    prior = [PlacementInstruction(field_name="rows", value=[{"a": "1"}])]
    assert diff_placements(prior, {"rows": [{"a": "2"}]}) == []


def test_learned_lines_are_replayed_into_later_prompts(db_session):
    from docforge.services.learning import corrections_fewshot, record_correction

    record_correction(
        db_session,
        owner_id="u1",
        document_type="report",
        kind="write",
        summaries=['the user cut "summary" to 40% of its length — write it more briefly'],
    )
    hints = corrections_fewshot(db_session, "u1", "report", kind="write")
    assert "write it more briefly" in hints
    assert "Learned conventions" in hints
    # Scoped per user and per kind.
    assert corrections_fewshot(db_session, "u2", "report", kind="write") == ""
    assert corrections_fewshot(db_session, "u1", "report", kind="classify") == ""
