"""The generate suite's notes cases agree with the corpus and with their own text."""

from __future__ import annotations

import dataclasses

import pytest

from evals.corpus.doc_types import SPECS
from evals.corpus.notes import (
    STYLES,
    TABLE_COLUMNS,
    field_kinds,
    load_notes,
    problems,
    source_values,
)

CASES = load_notes()


def test_every_pair_has_one_case_per_style():
    assert {(case.pair, case.style) for case in CASES} == {
        (pair, style) for pair in SPECS for style in STYLES}
    assert len(CASES) == 35


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_a_notes_case_is_consistent(case):
    assert problems(case) == []


def test_every_table_has_column_kinds_and_every_kind_is_known():
    for pair in SPECS:
        for logical, kind in field_kinds(pair).items():
            assert kind in ("text", "date", "money", "number", "person", "names", "free", "table")
            if kind == "table":
                assert len(TABLE_COLUMNS[logical]) == len(
                    next(b.headers for b in SPECS[pair].blocks if b.id == logical))


def test_the_styles_test_what_they_should():
    by_style = {style: [c for c in CASES if c.style == style] for style in STYLES}
    for case in by_style["missing"]:  # at least one field the notes don't give
        assert any(e.get("value", e.get("points", e.get("rows", ""))) is None
                   for e in case.expected.values()), case.id
    assert all(case.superseded for case in by_style["correction"])
    assert not any(case.superseded for case in CASES if case.style != "correction")


def _case(case_id):
    return next(case for case in CASES if case.id == case_id)


def _with(case, logical, **changes):
    expected = {**case.expected, logical: {**case.expected[logical], **changes}}
    return dataclasses.replace(case, expected=expected)


def test_the_check_finds_a_value_the_notes_dont_give():
    case = _case("invoice_en/missing")
    broken = _with(case, "field.vat_id", value="GB000000108")  # the source's, not in the notes
    assert any("not in the notes" in issue or "neither" in issue for issue in problems(broken))


def test_the_check_finds_a_typo_against_the_source_document():
    broken = _with(_case("nda_en/bullets"), "field.effective_date", value="23 March 2026")
    assert any("differs from the source" in issue for issue in problems(broken))


def test_the_check_finds_a_null_the_notes_do_give():
    broken = _with(_case("nda_en/bullets"), "field.party_b", value=None)
    assert any("source value" in issue for issue in problems(broken))


def test_the_check_finds_a_superseded_value_that_is_also_right():
    case = _case("service_agreement_en/correction")
    broken = dataclasses.replace(case, superseded={"field.monthly_fee": "€15,000.00"})
    assert any("also a right answer" in issue for issue in problems(broken))


def test_the_check_finds_a_wrong_table_cell_and_a_missing_field():
    case = _case("invoice_de/bullets")
    rows = [row[:] for row in case.expected["table.items"]["rows"]]
    rows[0][2] = ["1.100,00 €"]
    broken = _with(case, "table.items", rows=rows)
    assert any("row 1 cell 3" in issue for issue in problems(broken))
    expected = {k: v for k, v in case.expected.items() if k != "field.total"}
    assert any("missing ['field.total']" in issue
               for issue in problems(dataclasses.replace(case, expected=expected)))


def test_source_values_come_from_the_held_out_documents():
    values = source_values("nda_de", "held_02")
    assert values == {"field.effective_date": "01.04.2026",
                      "field.party_b": "Auerbrunn Maschinenbau AG",
                      "field.purpose": "Abgrenzung eines Managed-Security-Service"}
