"""Value comparison for the generate suite, on hand-picked forms of the same value."""

from __future__ import annotations

from datetime import date

import pytest

from evals.metrics.normalize import (
    appears_in,
    find_amounts,
    find_dates,
    is_placeholder,
    norm_text,
    parse_date,
    parse_money,
    parse_number,
    same,
    same_cell,
    split_names,
)


@pytest.mark.parametrize("text", [
    "23.11.2026", "23. 11. 2026", "2026-11-23", "23 November 2026", "23. November 2026",
    "November 23, 2026", "Nov 23rd 2026", "23rd of Nov. 2026", "23. Nov. 2026",
])
def test_a_date_in_any_common_form(text):
    assert parse_date(text) == date(2026, 11, 23)


def test_german_month_names_and_dates_inside_prose():
    notes = "Protokoll vom 10. Mai 2026; nächster Termin am 7. Juni 2026, nicht am 22.04."
    assert find_dates(notes) == [date(2026, 5, 10), date(2026, 6, 7)]  # no year: not a date
    assert parse_date("12. März 2026") == date(2026, 3, 12)


def test_a_value_with_two_different_dates_has_no_single_date():
    assert parse_date("21 April 2026 or 28 April 2026") is None
    assert parse_date("22.04.2026 (22 April 2026)") == date(2026, 4, 22)
    assert parse_date("next week") is None


@pytest.mark.parametrize("text, cents", [
    ("€11,950.00", 1195000), ("11.950,00 €", 1195000), ("EUR 11,950.00", 1195000),
    ("11,950.00 EUR", 1195000), ("€11.950", 1195000), ("€950", 95000), ("950,00 €", 95000),
    ("1.200,00", 120000), ("12.5 EUR", 1250), ("13550", 1355000),
])
def test_an_amount_in_any_grouping_and_decimal_convention(text, cents):
    assert parse_money(text) == cents


def test_amounts_in_prose_but_not_inside_dates():
    notes = "Am 23.11.2026: 3 x 1.200,00 € = 3.600,00 €, netto 13,730.00, Rabatt 12 %."
    assert find_amounts(notes) == [120000, 360000, 1373000]


def test_quantities():
    assert parse_number("3") == 3.0 and parse_number("2,5") == 2.5
    assert parse_number("3 days") is None


def test_text_ignores_case_punctuation_spacing_and_a_trailing_legal_form():
    assert norm_text("Retrospective – Identity  Management Rollout!") == (
        "retrospective identity management rollout")
    assert same("text", "Merrowind Retail Group", "Merrowind Retail Group Ltd")
    assert same("text", "Thistlecombe Energy Limited", "Thistlecombe Energy Ltd")
    assert same("text", "SA 2026 0438", "SA-2026-0438")
    assert not same("text", "SA-2026-0439", "SA-2026-0438")


def test_people_and_lists_of_people():
    assert same("person", "Dr. Farid Morandi", "Farid Morandi")
    assert split_names("Lukas Novak, Mira Ostwald and Ines Tamura") == {
        "lukas novak", "mira ostwald", "ines tamura"}
    assert same("names", "Mira Ostwald; Ines Tamura und Lukas Novak",
                "Lukas Novak, Mira Ostwald, Ines Tamura")
    assert not same("names", "Lukas Novak, Mira Ostwald", "Lukas Novak, Mira Ostwald, Ines Tamura")


def test_same_by_kind():
    assert same("date", "08.04.2026", "April 8, 2026")
    assert same("money", "13.350,00 €", "EUR 13,350.00")
    assert not same("money", "€13,350.01", "€13,350.00")
    assert same("number", "11", "11.0")
    assert not same("date", "", "8 April 2026") and not same("text", None, "x")


def test_a_table_cell_may_be_a_shorter_or_longer_label():
    assert same_cell("text", "Training", "Training workshop")
    assert same_cell("text", "Cloud hosting (monthly)", "Cloud hosting")
    assert not same_cell("text", "VAT", "Training")
    assert not same_cell("money", "€950", "€950.01")


@pytest.mark.parametrize("value", [
    "TBD", "tbc.", "To be confirmed", "To be assigned by legal", "Not yet fixed", "offen",
    "noch offen", "[Start Date]", "{{ start_date }}", "—", "TBD (legal will confirm)", "N/A",
])
def test_placeholders_stand_in_for_a_missing_value(value):
    assert is_placeholder(value)


@pytest.mark.parametrize("value", ["21 March 2026", "Quorvane Logistics Ltd", "Opening hours"])
def test_real_values_are_not_placeholders(value):
    assert not is_placeholder(value)


def test_appears_in_the_notes():
    notes = ("Kunde: Calvenna Health Partners Ltd. Vertrag SA-2026-0449 vom 16. März 2026, "
             "Vergütung 13.550,00 € im Monat. Teilnehmer: Mira Ostwald und Dr. Clara Haverkamp.")
    assert appears_in("date", "16 March 2026", notes)
    assert not appears_in("date", "6 April 2026", notes)
    assert appears_in("money", "€13,550.00", notes)
    assert not appears_in("money", "€13,500.00", notes)
    assert appears_in("text", "SA-2026-0449", notes)
    assert appears_in("text", "Calvenna Health Partners", notes)
    assert appears_in("text", "Calvenna Health", notes)  # a part of a name is in the notes too
    assert appears_in("person", "Clara Haverkamp", notes)
    assert appears_in("names", "Clara Haverkamp, Mira Ostwald", notes)
    assert not appears_in("names", "Clara Haverkamp, Ines Tamura", notes)
    assert not appears_in("text", "", notes)


def test_a_longer_value_put_together_from_the_notes_is_in_the_notes():
    notes = "Kunde: Calvenna Health Partners Ltd\nStart: 6. April 2026\nPreise / fees: on request"
    joined = "Kunde: Calvenna Health Partners Ltd Preise / fees: on request"  # line 2 left out
    assert appears_in("text", joined, notes)
    assert not appears_in("text", "Kunde: Calvenna Health Partners Ltd pays monthly", notes)
    assert not appears_in("text", "Calvenna Partners", notes)  # short: must be in one piece
