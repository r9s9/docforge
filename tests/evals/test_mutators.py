"""Each mutator changes exactly what its label says, and nothing else.

The expected result is worked out here from the spec's parameters, independently of the
mutator code, and compared with the document the mutator actually produced: every top-level
element's text, style and (for tables) every cell.
"""

from __future__ import annotations

import dataclasses
from functools import cache
from io import BytesIO

import pytest
from docx import Document

from docforge.structure_normalizer import build_extraction, walk_document
from evals.corpus.doc_types import SPECS
from evals.corpus.generator import build_document
from evals.corpus.mutators import MUTATORS, MutationError, applicable, clean_label, mutate
from evals.corpus.values import parse_date

BASE = 5  # held_01: mutations are always applied to held-out documents
CASES = [(pair, name) for pair in sorted(SPECS) for name in applicable(SPECS[pair])]
TEXT_EDITS = {
    "change_liability_cap",
    "change_governing_law",
    "change_notice_period",
    "change_payment_terms",
    "fix_typo",
    "whitespace_quotes",
}


@cache
def _base(pair: str) -> tuple[bytes, list[dict]]:
    return build_document(SPECS[pair], BASE)


@cache
def skeleton(data: bytes) -> list[tuple]:
    """Top-level elements in walk order: (scope, kind, text or table cells, style)."""
    items = []
    for node in walk_document(Document(BytesIO(data))):
        if node.parent_node_id is not None:
            continue
        scope = node.scope or "body"
        if node.kind == "table":
            cells = tuple(tuple(cell.text for cell in row.cells) for row in node.obj.rows)
            items.append((scope, "table", cells, ""))
        else:
            style = node.obj.style.name if node.obj.style is not None else ""
            items.append((scope, "paragraph", node.obj.text, style))
    return items


def expected_skeleton(before: list[tuple], truth: list[dict], name: str, spec) -> list[tuple]:
    """What the document should look like after mutation ``name``, from the spec alone."""
    items = list(before)
    params = spec.mutations[name]
    position = {e["id"]: e["locator"]["block"] for e in truth if e["locator"]["scope"] == "body"}
    by_id = {e["id"]: e for e in truth}

    def retext(logical_id: str, text) -> None:
        scope, kind, _, style = items[position[logical_id]]
        items[position[logical_id]] = (scope, kind, text, style)

    if name in TEXT_EDITS:
        text = items[position[params["target"]]][2]
        for old, new in params["replace"]:
            text = text.replace(old, new, 1)
        retext(params["target"], text)
    elif name == "heading_caps":
        retext(params["target"], items[position[params["target"]]][2].upper())
    elif name in ("empty_field", "date_format", "invalid_value"):
        element = by_id[params["target"]]
        if name == "empty_field":
            value = ""
        elif name == "date_format":
            value = parse_date(element["value"], spec.lang).isoformat()
        else:
            value = params["value"]
        retext(params["target"], f"{element['label']}: {value}")
    elif name == "delete_clause":
        for index in sorted((position[t] for t in params["targets"]), reverse=True):
            del items[index]
    elif name == "remove_row":
        retext(params["target"], items[position[params["target"]]][2][:-1])
    elif name == "remove_column":
        rows = items[position[params["target"]]][2]
        column = params["column"]
        retext(params["target"], tuple(r[:column] + r[column + 1 :] for r in rows))
    elif name == "delete_table":
        del items[position[params["target"]]]
    elif name == "reorder_sections":
        start, end = position[params["first"][0]], position[params["first"][-1]]
        second_end = position[params["second"][-1]]
        assert end + 1 == position[params["second"][0]], "sections must be adjacent"
        items = (
            items[:start]
            + items[end + 1 : second_end + 1]
            + items[start : end + 1]
            + items[second_end + 1 :]
        )
    elif name in ("insert_benign", "insert_material"):
        items.insert(position[params["after"]] + 1, ("body", "paragraph", params["text"], "Normal"))
    else:
        raise AssertionError(f"no expectation written for {name}")
    return items


@pytest.mark.parametrize(("pair", "name"), CASES)
def test_mutator_changes_exactly_its_target(pair, name):
    spec = SPECS[pair]
    data, truth = _base(pair)
    mutated, _label = mutate(name, data, truth, spec)
    assert skeleton(mutated) == expected_skeleton(skeleton(data), truth, name, spec)


@pytest.mark.parametrize(("pair", "name"), CASES)
def test_label_is_complete_and_consistent(pair, name):
    spec = SPECS[pair]
    data, truth = _base(pair)
    _mutated, label = mutate(name, data, truth, spec)
    assert set(label) == {
        "mutator", "targets", "expected_kind", "material", "rule_dependent", "fixable", "detail"
    }
    assert label["mutator"] == name
    assert label["expected_kind"] == MUTATORS[name].expected_kind
    assert isinstance(label["material"], bool)
    ids = {element["id"] for element in truth}
    assert set(label["targets"]) <= ids
    assert label["targets"] or name.startswith("insert_")


@pytest.mark.parametrize(("pair", "name"), CASES)
def test_docforge_can_read_every_mutated_document(pair, name, tmp_path):
    spec = SPECS[pair]
    data, truth = _base(pair)
    mutated, _label = mutate(name, data, truth, spec)
    path = tmp_path / "mutated.docx"
    path.write_bytes(mutated)
    extraction = build_extraction(str(path), document_id="m", filename="mutated.docx")
    assert extraction.elements


def test_mutations_are_deterministic():
    spec = SPECS["service_agreement_de"]
    data, truth = _base("service_agreement_de")
    assert mutate("reorder_sections", data, truth, spec) == mutate(
        "reorder_sections", data, truth, spec
    )


def test_materiality_comes_from_the_ground_truth_where_the_spec_decides():
    def material(pair: str, name: str) -> bool:
        data, truth = _base(pair)
        return mutate(name, data, truth, SPECS[pair])[1]["material"]

    assert material("service_agreement_en", "delete_clause") is True  # confidentiality
    assert material("minutes_en", "delete_clause") is False  # procedural distribution note
    assert material("invoice_de", "remove_row") is True  # an invoice line
    assert material("nda_en", "insert_benign") is False
    assert material("nda_en", "insert_material") is True


def test_a_replacement_that_does_not_fit_the_text_is_refused():
    spec = SPECS["nda_en"]
    broken = dataclasses.replace(
        spec,
        mutations={"fix_typo": {"target": "clause.obligations", "replace": [["absent", "x"]]}},
    )
    data, truth = _base("nda_en")
    with pytest.raises(MutationError, match="absent"):
        mutate("fix_typo", data, truth, broken)


def test_clean_label_marks_a_control():
    label = clean_label()
    assert label["mutator"] == "none" and label["targets"] == [] and label["material"] is False


def test_every_mutator_is_used_by_some_document_type():
    used = {name for pair in SPECS for name in applicable(SPECS[pair])}
    assert used == set(MUTATORS)
