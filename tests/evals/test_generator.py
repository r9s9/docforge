"""The corpus builder is deterministic, and gives DocForge what it needs to tell fields from
boilerplate: every field varies across a type's examples, and no boilerplate line does."""

from __future__ import annotations

import re
from datetime import date
from functools import cache

import pytest

from evals.corpus.doc_types import SPECS
from evals.corpus.generator import (
    EXAMPLES,
    HELD_OUT,
    all_doc_ids,
    build_document,
    content_hash,
    doc_id,
    doc_index,
)
from evals.corpus.values import fmt_date, fmt_money, parse_date, pick

PAIRS = sorted(SPECS)


@cache
def _truths(pair: str) -> list[list[dict]]:
    return [build_document(SPECS[pair], i)[1] for i in range(EXAMPLES + HELD_OUT)]


@pytest.mark.parametrize("pair", PAIRS)
def test_builds_are_byte_identical(pair):
    first, truth_first = build_document(SPECS[pair], 3)
    second, truth_second = build_document(SPECS[pair], 3)
    assert first == second
    assert truth_first == truth_second
    assert content_hash(first) == content_hash(second)


@pytest.mark.parametrize("pair", PAIRS)
def test_every_field_differs_in_every_example(pair):
    examples = _truths(pair)[:EXAMPLES]
    for position, element in enumerate(examples[0]):
        if element["kind"] not in ("field", "table"):
            continue
        key = "rows" if element["kind"] == "table" else "value"
        values = {repr(truth[position][key]) for truth in examples}
        assert len(values) == EXAMPLES, f"{pair} {element['id']} repeats a value: {values}"


@pytest.mark.parametrize("pair", PAIRS)
def test_boilerplate_is_identical_in_every_document(pair):
    truths = _truths(pair)
    for position, element in enumerate(truths[0]):
        if element["kind"] in ("fixed", "auto"):
            assert {truth[position]["text"] for truth in truths} == {element["text"]}


@pytest.mark.parametrize("pair", PAIRS)
def test_every_mutation_names_existing_elements_and_text(pair):
    spec = SPECS[pair]
    blocks = {block.id: block for block in spec.blocks}
    for name, params in spec.mutations.items():
        for key in ("target", "after"):
            if key in params:
                assert params[key] in blocks, f"{pair} {name}: unknown {params[key]}"
        for key in ("targets", "first", "second"):
            for target in params.get(key, []):
                assert target in blocks, f"{pair} {name}: unknown {target}"
        for old, _new in params.get("replace", []):
            assert old in blocks[params["target"]].text, f"{pair} {name}: {old!r} not in text"


def test_document_ids_round_trip():
    assert [doc_index(d) for d in all_doc_ids()] == list(range(EXAMPLES + HELD_OUT))
    assert (doc_id(0), doc_id(EXAMPLES - 1), doc_id(EXAMPLES)) == ("ex_01", "ex_05", "held_01")


def test_date_and_money_formats():
    assert fmt_date(date(2026, 11, 23), "de") == "23.11.2026"
    assert fmt_date(date(2026, 3, 4), "en") == "4 March 2026"
    assert parse_date("23.11.2026", "de") == date(2026, 11, 23)
    assert parse_date("4 March 2026", "en") == date(2026, 3, 4)
    assert fmt_money(123_456, "de") == "1.234,56 €"
    assert fmt_money(123_456, "en") == "€1,234.56"
    assert fmt_money(5, "en") == "€0.05"


def test_pick_gives_distinct_items_up_to_the_pool_size():
    pool = list(range(8))
    assert len({pick(pool, "pair", "key", i) for i in range(8)}) == 8


def _cents(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits)


@pytest.mark.parametrize("pair", ["invoice_en", "invoice_de"])
def test_invoice_amounts_add_up(pair):
    for truth in _truths(pair):
        by_id = {element["id"]: element for element in truth}
        rows = by_id["table.items"]["rows"]
        assert sum(_cents(row[3]) for row in rows) == _cents(by_id["field.subtotal"]["value"])
        subtotal = _cents(by_id["field.subtotal"]["value"])
        vat = _cents(by_id["field.vat"]["value"])
        assert subtotal + vat == _cents(by_id["field.total"]["value"])
