"""Analyze metrics on tiny cases worked out by hand."""

from __future__ import annotations

import pytest

from evals.metrics.analyze import (
    case_outcomes,
    category,
    element_outcome,
    f1,
    quality,
    shared_metrics,
    stability,
    summarize,
    template_layout,
    type_ok,
)
from evals.metrics.comply import rate


def _field(id_, field_type="text", label=None, block=0):
    element = {"id": id_, "kind": "field", "field_type": field_type,
               "locator": {"scope": "body", "block": block}}
    if label:
        element["label"] = label
    return element


def _fixed(id_, block=0):
    return {"id": id_, "kind": "fixed", "locator": {"scope": "body", "block": block}}


def _info(id_="info.doc", block=0):
    """A two-row information block: "Classification | Confidential", "Owner | <value>"."""
    def cell(cid, kind, row, col, **extra):
        return {"id": cid, "kind": kind, "cell": {"row": row, "col": col}, **extra}
    return {"id": id_, "kind": "info_table", "locator": {"scope": "body", "block": block},
            "rows": [["Classification", "Confidential"], ["Owner", "Ines Tamura"]],
            "cells": [cell("cell.class.label", "fixed", 0, 0), cell("cell.class", "fixed", 0, 1),
                      cell("cell.owner.label", "fixed", 1, 0),
                      cell("cell.owner", "field", 1, 1, field_type="person")]}


@pytest.mark.parametrize(("cls", "want"), [
    ("FIXED", "fixed"), ("DYNAMIC_DATE", "field"), ("DYNAMIC_TEXT", "field"),
    ("REPEATABLE_SECTION", "field"), ("REPEATABLE_BLOCK", "field"),
    ("REPEATABLE_TABLE", "table"), ("AUTO_FIELD", "auto"), ("UNKNOWN", "unknown"),
    (None, "unknown"),
])
def test_what_a_classification_makes_of_an_element(cls, want):
    assert category(cls) == want


def test_field_types_follow_the_design_map():
    assert type_ok("money", "number") and not type_ok("money", "text")  # H9: German amounts
    assert type_ok("multiline_text", "text") and type_ok("multiline_text", "multiline_text")
    assert not type_ok("text", "multiline_text")
    assert not type_ok("person", "text")
    assert type_ok("date", None) is None


def test_element_outcomes():
    assert element_outcome(_fixed("clause"), {"class": "FIXED"})["outcome"] == "kept"
    assert element_outcome(_fixed("clause"), {"class": "DYNAMIC_TEXT"})["outcome"] == (
        "became_field")
    assert element_outcome(_fixed("clause"), {"class": "UNKNOWN"})["outcome"] == "other"
    found = element_outcome(_field("field.total", "money"),
                            {"class": "DYNAMIC_NUMBER", "field_type": "number"})
    assert (found["outcome"], found["type_ok"]) == ("found", True)
    missed = element_outcome(_field("field.total", "money"),
                             {"class": "FIXED", "field_type": "number"})
    assert (missed["outcome"], missed["predicted_type"], missed["type_ok"]) == (
        "missed", None, None)  # a missed field has no type to judge
    table = {"id": "table.items", "kind": "table", "headers": ["Item", "Qty"],
             "locator": {"scope": "body", "block": 3}}
    assert element_outcome(table, {"class": "REPEATABLE_TABLE",
                                   "columns": ["item", "QTY"]})["outcome"] == "detected"
    assert element_outcome(table, {"class": "REPEATABLE_TABLE",
                                   "columns": ["Item"]})["outcome"] == "wrong_header"
    assert element_outcome(table, {"class": "FIXED"})["outcome"] == "missed"
    auto = {"id": "footer.page", "kind": "auto", "locator": {"scope": "footer:0", "block": 0}}
    assert element_outcome(auto, {"class": "AUTO_FIELD"})["outcome"] == "auto"


def test_a_looped_information_block_repeats_every_row_but_the_first():
    out = case_outcomes([_info()], {"info.doc": {"class": "REPEATABLE_TABLE"},
                                    "cell.class.label": {"class": "FIXED"},
                                    "cell.class": {"class": "FIXED"},
                                    "cell.owner.label": {"class": "FIXED"},
                                    "cell.owner": {"class": "FIXED"}})
    assert out["info.doc"]["outcome"] == "looped"
    assert out["cell.class.label"]["outcome"] == out["cell.class"]["outcome"] == "kept"  # row 0
    assert out["cell.owner.label"]["outcome"] == "became_field"  # a label turned row data
    assert out["cell.owner"]["outcome"] == "found"  # the value is fillable, if by accident


def test_a_frozen_a_form_and_a_partial_information_block():
    fixed = {cid: {"class": "FIXED"} for cid in ("info.doc", "cell.class.label", "cell.class",
                                                 "cell.owner.label", "cell.owner")}
    frozen = case_outcomes([_info()], fixed)
    assert frozen["info.doc"]["outcome"] == "frozen" and frozen["cell.owner"]["outcome"] == (
        "missed")
    form = case_outcomes([_info()], {**fixed, "cell.owner": {"class": "DYNAMIC_PERSON"}})
    assert form["info.doc"]["outcome"] == "form"
    partial = case_outcomes([_info()], {**fixed, "cell.class": {"class": "DYNAMIC_TEXT"}})
    assert partial["info.doc"]["outcome"] == "partial"


def _record(outcomes, *, k=2, pair="invoice_en", lang="en", group="examples", **extra):
    return {"id": f"{pair}/k{k}", "pair": pair, "lang": lang, "k": k, "group": group,
            "error": None, "outcomes": outcomes, "layout": {"preserved": True}, **extra}


def test_precision_recall_and_boilerplate_by_hand():
    # 3 fields (2 found, 1 missed), 4 fixed elements (1 became a field), 1 table (detected)
    outcomes = {
        "f1": {"kind": "field", "field_type": "date", "outcome": "found", "type_ok": True},
        "f2": {"kind": "field", "field_type": "money", "outcome": "found", "type_ok": False},
        "f3": {"kind": "field", "field_type": "text", "outcome": "missed", "type_ok": None},
        "x1": {"kind": "fixed", "outcome": "kept"},
        "x2": {"kind": "fixed", "outcome": "kept"},
        "x3": {"kind": "fixed", "outcome": "kept"},
        "x4": {"kind": "fixed", "outcome": "became_field"},
        "t1": {"kind": "table", "outcome": "detected"},
    }
    metrics = quality([_record(outcomes)])
    assert metrics["field_precision"] == rate(2, 3)  # 2 TP, 1 FP
    assert metrics["field_recall"] == rate(2, 3)  # 2 TP, 1 FN
    assert metrics["field_f1"] == {"value": 4 / 6, "tp": 2, "fp": 1, "fn": 1}
    assert metrics["boilerplate_kept"] == rate(3, 4)
    assert metrics["type_accuracy"] == rate(1, 2)
    assert metrics["types_by_kind"] == {"date": rate(1, 1), "money": rate(0, 1)}
    assert metrics["types_by_lang"] == {"en": rate(1, 2)}
    assert metrics["tables_detected"] == rate(1, 1)
    assert f1(0, 0, 0)["value"] is None


def test_information_block_cells_count_in_precision_recall_but_not_in_types():
    looped = case_outcomes([_info()], {"info.doc": {"class": "REPEATABLE_TABLE"}})
    metrics = quality([_record(looped)])
    # cells: owner value found (TP); owner label became row data (FP); row 0 kept (2 fixed)
    assert metrics["field_f1"] == {"value": 2 / 3, "tp": 1, "fp": 1, "fn": 0}
    assert metrics["boilerplate_kept"] == rate(2, 3)
    assert metrics["info_tables"] == {"looped": 1}
    assert metrics["info_values_found"] == rate(1, 1)
    assert metrics["type_accuracy"] == rate(0, 0)  # cells have no DocForge field type


def test_the_shared_value_check():
    records = [
        _record({"field.customer": {"kind": "field", "field_type": "text", "outcome": "missed"}},
                group="shared", shared_field="field.customer"),
        _record({"field.party_b": {"kind": "field", "field_type": "text", "outcome": "found"}},
                group="shared", pair="nda_en", shared_field="field.party_b"),
    ]
    out = shared_metrics(records)
    assert out["shared_field_found"] == rate(1, 2)
    assert out["missed"] == ["invoice_en"]


def test_summarize_groups_cases_by_number_of_examples():
    kept = {"x": {"kind": "fixed", "outcome": "kept"},
            "f": {"kind": "field", "field_type": "text", "outcome": "found", "type_ok": True}}
    lost = {"x": {"kind": "fixed", "outcome": "became_field"},
            "f": {"kind": "field", "field_type": "text", "outcome": "found", "type_ok": True}}
    records = [_record(lost, k=1, analyze_ms=10.0), _record(kept, k=2, analyze_ms=30.0),
               _record(kept, k=2, pair="nda_en", analyze_ms=20.0),
               {**_record({}, k=3), "error": "boom", "outcomes": None}]
    out = summarize(records)
    assert out["cases"] == 4 and out["error_rate"] == rate(1, 4)
    assert out["by_k"]["1"]["boilerplate_kept"] == rate(0, 1)
    assert out["by_k"]["2"]["boilerplate_kept"] == rate(2, 2)
    assert out["by_k"]["3"]["cases"] == 0 and out["by_k"]["5"]["cases"] == 0
    assert out["by_pair"]["invoice_en"] == {
        "1": {"field_f1": 2 / 3, "boilerplate_kept": 0.0},
        "2": {"field_f1": 1.0, "boilerplate_kept": 1.0}}
    assert out["analyze_ms_p50"] == 20.0 and out["shared"] is None and out["ai"] is None


def test_stability_counts_elements_whose_outcome_never_changes():
    base = _record({"a": {"kind": "fixed", "outcome": "kept"},
                    "b": {"kind": "field", "outcome": "found"}})
    again = _record({"a": {"kind": "fixed", "outcome": "kept"},
                     "b": {"kind": "field", "outcome": "missed"}})
    out = stability([base], [again, again])
    assert out["outcome_agreement"] == rate(1, 2)
    assert (out["cases"], out["runs_per_case"]) == (1, 3)
    assert stability([base], []) is None


def _skeleton(*items):
    return [("body", *item) for item in items]


def test_the_template_layout_check():
    truth = [_fixed("title", 0), _field("field.date", "date", label="Date", block=1),
             _fixed("clause", 2), {"id": "table.items", "kind": "table", "headers": ["Item"],
                                   "locator": {"scope": "body", "block": 3}}]
    source = _skeleton(("paragraph", "INVOICE", "Normal"),
                       ("paragraph", "Date: 4 March 2026", "Normal"),
                       ("paragraph", "Payment within 14 days.", "Normal"),
                       ("table", (("Item",), ("Training",)), ""))
    outcomes = {"title": {"outcome": "kept"}, "clause": {"outcome": "kept"}}
    template = _skeleton(("paragraph", "INVOICE", "Normal"),
                         ("paragraph", "Date: {{ date }}", "Normal"),
                         ("paragraph", "{%p if _show_x %}", "Normal"),  # a marker: allowed
                         ("paragraph", "Payment within 14 days.", "Normal"),
                         ("table", (("Item",), ("{%tr for row in items %}",)), ""))
    assert template_layout(truth, source, template, outcomes) == []
    changed = [*template[:3], ("body", "paragraph", "Payment within 30 days.", "Normal"),
               template[4]]
    assert template_layout(truth, source, changed, outcomes) == ["clause: missing or out of order"]
    # a clause the analysis turned into a field may carry a tag instead of its text
    tagged = [*template[:3], ("body", "paragraph", "{{ payment }}", "Normal"), template[4]]
    assert template_layout(truth, source, tagged, {**outcomes, "clause": {
        "outcome": "became_field"}}) == []
    restyled = [template[0], ("body", "paragraph", "Date: {{ date }}", "Heading 1"),
                *template[2:]]
    assert template_layout(truth, source, restyled, outcomes) == [
        "field.date: missing or out of order"]


def test_every_row_of_an_information_block_must_survive_in_the_template():
    block = {**_info(block=0), "rows": [["Classification", "Confidential"], ["Owner", "x"],
                                         ["Version", "1.0"]]}
    source = _skeleton(("table", (("Classification", "Confidential"), ("Owner", "Ines Tamura"),
                                  ("Version", "1.0")), ""))
    frozen = source  # values frozen, but every row is still there
    looped = _skeleton(("table", (("Classification", "Confidential"),
                                  ("{%tr for item in rows %}", ""),
                                  ("{{ item.classification }}", "{{ item.confidential }}"),
                                  ("{%tr endfor %}", "")), ""))
    assert template_layout([block], source, frozen, {}) == []
    assert template_layout([block], source, looped, {}) == ["info.doc: rows lost"]
