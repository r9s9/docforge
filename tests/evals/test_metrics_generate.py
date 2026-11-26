"""Generate metrics on tiny cases whose answers were worked out by hand."""

from __future__ import annotations

import pytest

from evals.metrics.comply import rate
from evals.metrics.generate import (
    field_metrics,
    field_outcome,
    form_kept,
    layout_problems,
    stability,
    summarize,
    table_outcome,
)

NOTES = ("Invoice INV-2026-0168 for Thistlecombe Energy Ltd, dated 24 April 2026 - correction: "
         "25 April 2026. Due 25 May 2026. 7 x consulting services at €150.00 = €1,050.00.")


def given(value, *accept):
    return {"value": value, "accept": list(accept)}


def test_a_value_in_another_form_is_correct_and_its_form_is_judged_separately():
    english = field_outcome("date", "25.04.2026", given("25 April 2026"), NOTES, lang="en")
    assert english["outcome"] == "correct" and english["form_kept"] is False
    german = field_outcome("date", "25.04.2026", given("25.04.2026"), NOTES, lang="de")
    assert german["form_kept"] is True
    assert form_kept("money", "€1,050.00", "en") is True
    assert form_kept("money", "1.050,00 €", "en") is False
    assert form_kept("text", "anything", "en") is None


def test_an_accepted_form_is_correct():
    outcome = field_outcome("text", "Thistlecombe Energy", given("Thistlecombe Energy Ltd"), NOTES)
    assert outcome["outcome"] == "correct"
    meeting = given("Retrospective – identity management rollout",
                    "Retrospective on the identity management rollout")
    written = "Retrospective on the Identity Management Rollout"
    assert field_outcome("text", written, meeting, NOTES)["outcome"] == "correct"


def test_empty_and_placeholder_values():
    assert field_outcome("text", None, given(None), NOTES)["outcome"] == "correctly_empty"
    tbd = field_outcome("text", "TBD", given(None), NOTES)
    assert tbd["outcome"] == "correctly_empty" and tbd["placeholder"] is True
    assert field_outcome("date", "", given("25 May 2026"), NOTES)["outcome"] == "omitted"
    assert field_outcome("date", "[Due Date]", given("25 May 2026"), NOTES)["outcome"] == "omitted"


def test_a_value_from_the_notes_in_the_wrong_place_or_a_corrected_one_is_grounded_but_wrong():
    swapped = field_outcome("date", "25 May 2026", given("25 April 2026"), NOTES)
    assert swapped["outcome"] == "grounded_wrong" and swapped["superseded"] is False
    stale = field_outcome("date", "24 April 2026", given("25 April 2026"), NOTES,
                          superseded="24 April 2026")
    assert stale["outcome"] == "grounded_wrong" and stale["superseded"] is True


def test_a_value_in_no_form_in_the_notes_is_a_hallucination_flagged_or_not():
    invented = field_outcome("text", "GB000000109", given(None), NOTES)
    assert invented["outcome"] == "unsupported" and invented["ai_drafted"] is False
    drafted = field_outcome("money", "€1,260.00", given("€1,050.00"), NOTES, ai_drafted=True)
    assert drafted["outcome"] == "unsupported" and drafted["ai_drafted"] is True


ITEMS = {
    "columns": ("text", "number", "money", "money"),
    "rows": [[["Consulting services"], ["7"], ["€150.00"], ["€1,050.00"]],
             [["Security review"], ["1"], ["€1,200.00"], ["€1,200.00"]]],
}
ITEM_NOTES = "consulting services 7 x €150.00 = €1,050.00; security review 1 x €1,200.00"


def test_rows_are_matched_even_when_reordered():
    written = [["Security review", "1", "€1,200.00", "€1,200.00"],
               ["Consulting", "7", "150,00 €", "€1,050.00"]]
    t = table_outcome(ITEMS, written, ITEM_NOTES)
    assert t["row_count_ok"] is True
    assert (t["cells_expected"], t["cells_correct"], t["cells_unsupported"]) == (8, 8, 0)


def test_a_missing_row_and_an_invented_row():
    written = [["Consulting services", "7", "€150.00", "€1,050.00"],
               ["Travel expenses", "1", "€300.00", "€300.00"]]
    t = table_outcome(ITEMS, written, ITEM_NOTES)
    assert t["row_count_ok"] is True  # two rows, but the wrong second one
    assert t["cells_correct"] == 5  # row 1: 4 cells; row 2 matched only on the quantity "1"
    assert t["cells_unsupported"] == 3  # "Travel expenses", "€300.00" twice; "1" is in the notes
    short = table_outcome(ITEMS, written[:1], ITEM_NOTES)
    assert short["row_count_ok"] is False and short["cells_correct"] == 4


def test_a_table_the_notes_dont_have():
    t = table_outcome({"columns": ("text", "text", "money"), "rows": None},
                      [["Training", "per session", "€950.00"]], "no fees agreed")
    assert t["invented"] is True and t["cells_unsupported"] == 3
    empty = table_outcome({"columns": ("text", "text", "money"), "rows": None}, [["", "", ""]],
                          "x")
    assert empty["invented"] is False and empty["rows_written"] == 0


TRUTH = [
    {"id": "title", "kind": "fixed", "locator": {"scope": "body", "block": 0}},
    {"id": "field.date", "kind": "field", "label": "Date",
     "locator": {"scope": "body", "block": 1}},
    {"id": "text.agenda", "kind": "field", "locator": {"scope": "body", "block": 2}},
    {"id": "table.actions", "kind": "table", "locator": {"scope": "body", "block": 3}},
]
TEMPLATE = [
    ("body", "paragraph", "MINUTES", "Title"),
    ("body", "paragraph", "Date: 2 March 2026", "Normal"),
    ("body", "paragraph", "Old agenda", "Normal"),
    ("body", "table", (("Action", "Owner"), ("Plan", "Ann")), ""),
]


def test_layout_keeps_fixed_text_labels_and_table_headers_in_order():
    output = [
        ("body", "paragraph", "MINUTES", "Title"),
        ("body", "paragraph", "Date: 22 May 2026", "Normal"),
        ("body", "paragraph", "First agenda line", "Normal"),
        ("body", "paragraph", "Second agenda line", "Normal"),  # extra prose is fine
        ("body", "table", (("Action", "Owner"), ("A", "B"), ("C", "D")), ""),
    ]
    assert layout_problems(TRUTH, TEMPLATE, output) == []


def test_layout_problems_name_what_was_lost():
    retitled = [("body", "paragraph", "Minutes", "Title"), *TEMPLATE[1:]]
    assert layout_problems(TRUTH, TEMPLATE, retitled) == ["title: missing or out of order"]
    unlabelled = [TEMPLATE[0], ("body", "paragraph", "22 May 2026", "Normal"), *TEMPLATE[2:]]
    assert layout_problems(TRUTH, TEMPLATE, unlabelled) == ["field.date: missing or out of order"]
    new_header = [*TEMPLATE[:3], ("body", "table", (("Task", "Owner"),), "")]
    assert layout_problems(TRUTH, TEMPLATE, new_header) == [
        "table.actions: missing or out of order"]


def _field(outcome, expected="x", value="x", drafted=False):
    return {"kind": "text", "value": value, "expected": expected, "outcome": outcome,
            "ai_drafted": drafted, "placeholder": False, "superseded": False, "form_kept": None}


def test_field_metrics_by_hand():
    records = [{"id": "a", "style": "missing", "fields": {
        "f1": _field("correct"),
        "f2": _field("omitted", value=None),
        "f3": _field("unsupported", expected=None, value="made up", drafted=True),
        "f4": _field("correctly_empty", expected=None, value=None),
        "f5": _field("grounded_wrong"),
        "f6": _field("unsupported", value="also made up"),
    }}]
    m = field_metrics(records)
    # given: f1 f2 f5 f6 -> 1 correct, 1 omitted of 4. Written: f1 f3 f5 f6.
    assert m["accuracy"] == rate(1, 4) and m["omission_rate"] == rate(1, 4)
    assert m["hallucination_rate"] == rate(2, 4)
    assert m["hallucinations_flagged"] == rate(1, 2)
    assert m["grounded_wrong_rate"] == rate(1, 4)
    assert m["correctly_empty_rate"] == rate(1, 2)


def test_stability_compares_field_outcomes_across_repeats():
    base = {"id": "c", "fields": {"f1": _field("correct"), "f2": _field("unsupported", value="y")}}
    repeats = [{"id": "c", "fields": {"f1": _field("correct"), "f2": _field("omitted", value="")}},
               {"id": "c", "fields": {"f1": _field("correct"), "f2": _field("unsupported",
                                                                             value="y")}}]
    s = stability([base], repeats)
    assert s["runs_per_case"] == 3 and s["outcome_agreement"] == rate(1, 2)
    assert s["value_agreement"] == rate(1, 2)
    assert stability([base], []) is None


def test_summary_of_a_small_run_without_ai():
    records = [
        {"id": "a", "style": "bullets", "ai": False, "generate_ms": 10.0, "error": None,
         "fields": {"f": _field("correct")}, "tables": {}, "free": {},
         "routing": {"source": "heuristic"}, "review": {"ran": False},
         "layout": {"preserved": True}},
        {"id": "b", "style": "email", "ai": False, "generate_ms": None, "error": "boom"},
    ]
    s = summarize(records)
    assert s["cases"] == 2 and s["error_rate"] == rate(1, 2)
    assert s["fields"]["accuracy"] == rate(1, 1) and s["ai"] is None
    assert s["pipeline"]["routing_source"] == {"heuristic": 1}
    assert s["by_style"]["bullets"]["accuracy"] == rate(1, 1)
    assert s["generate_ms_p50"] == pytest.approx(10.0)
