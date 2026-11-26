"""Comply metrics on tiny cases whose answers were worked out by hand."""

from __future__ import annotations

import pytest

from evals.metrics.comply import attribute, auc, percentile, rate, summarize


def record(
    mutator: str,
    *,
    material: bool,
    targets: tuple[str, ...] = (),
    kind: str | None = None,
    diffs: tuple[tuple[str, str, str | None], ...] = (),
    extras: tuple[str, ...] = (),
    score: float = 100.0,
    grade: str = "pass",
    fixable: bool = False,
    fix: dict | None = None,
    error: str | None = None,
    detail: dict | None = None,
    check_ms: float = 10.0,
) -> dict:
    return {
        "label": {
            "mutator": mutator,
            "targets": list(targets),
            "expected_kind": kind,
            "material": material,
            "rule_dependent": False,
            "fixable": fixable,
            "detail": detail or {},
        },
        "differences": [{"kind": k, "severity": s, "logical_id": lid} for k, s, lid in diffs],
        "extras": list(extras),
        "score": score,
        "grade": grade,
        "fix": fix,
        "error": error,
        "check_ms": check_ms,
    }


def test_rate_keeps_its_counts_and_has_no_value_without_a_denominator():
    assert rate(1, 4) == {"value": 0.25, "num": 1, "den": 4}
    assert rate(0, 0) == {"value": None, "num": 0, "den": 0}


def test_a_difference_on_the_target_with_the_expected_kind_is_found_and_right():
    r = record("change_liability_cap", material=True, targets=("clause.x",), kind="changed_fixed",
               diffs=(("changed_fixed", "warning", "clause.x"),))
    assert attribute(r) == {"found": True, "kind_ok": True, "alarm": True, "alarms": 1,
                            "spurious": 0}


def test_a_wrong_kind_still_counts_as_found_and_other_nodes_are_spurious():
    r = record("delete_clause", material=True, targets=("clause.x",), kind="missing_fixed",
               diffs=(("changed_fixed", "warning", "clause.x"), ("missing_fixed", "error", "y")))
    outcome = attribute(r)
    assert (outcome["found"], outcome["kind_ok"], outcome["spurious"], outcome["alarms"]) == (
        True, False, 1, 2
    )


def test_a_difference_elsewhere_does_not_find_the_deviation():
    r = record("change_notice_period", material=True, targets=("clause.term",),
               kind="changed_fixed", diffs=(("changed_fixed", "warning", "clause.other"),))
    outcome = attribute(r)
    assert outcome["found"] is False and outcome["kind_ok"] is None and outcome["spurious"] == 1


def test_an_insertion_is_found_only_through_an_extra_row_with_its_text():
    detail = {"text": "The Supplier accepts unlimited liability."}
    seen = record("insert_material", material=True, detail=detail,
                  extras=("the supplier  accepts unlimited liability.",))
    unseen = record("insert_material", material=True, detail=detail,
                    diffs=(("changed_fixed", "warning", "clause.liability"),))
    assert attribute(seen)["found"] is True and attribute(seen)["kind_ok"] is None
    assert attribute(unseen)["found"] is False and attribute(unseen)["spurious"] == 1


def test_info_differences_are_not_alarms():
    r = record("none", material=False, diffs=(("missing_field", "info", "field.optional"),))
    assert attribute(r)["alarm"] is False


def test_auc_counts_ties_as_half():
    # pairs: 100>80, 100>90, 90>80, 90=90 -> (1 + 1 + 1 + 0.5) / 4
    assert auc([100, 90], [80, 90]) == 0.875
    assert auc([], [1.0]) is None


def test_percentile_interpolates_between_ranks():
    assert percentile([40, 10, 30, 20], 0.5) == 25
    assert percentile([10, 20, 30, 40], 0.95) == pytest.approx(38.5)
    assert percentile([7], 0.95) == 7
    assert percentile([], 0.5) is None


def test_summary_of_a_small_run():
    records = [
        record("change_liability_cap", material=True, targets=("c",), kind="changed_fixed",
               diffs=(("changed_fixed", "warning", "c"),), score=92.0),
        record("change_notice_period", material=True, targets=("t",), kind="changed_fixed",
               score=100.0),
        record("heading_caps", material=False, targets=("h",), kind="changed_fixed",
               diffs=(("changed_fixed", "warning", "h"),), score=97.0),
        record("fix_typo", material=False, targets=("c",), kind="changed_fixed"),
        record("none", material=False, score=100.0),
        record("none", material=False, diffs=(("missing_fixed", "error", "x"),), score=80.0,
               grade="warning"),
        record("delete_table", material=True, targets=("tbl",), kind="missing_table",
               error="ValueError: boom"),
    ]
    s = summarize(records)
    assert s["cases"] == 7
    assert s["detection_recall"] == rate(1, 2)  # the errored case is left out
    assert s["kind_accuracy"] == rate(1, 1)
    assert s["benign_alarm_rate"] == rate(1, 2)
    assert s["false_alarm_rate_clean"] == rate(1, 2)
    assert s["mean_alarms_clean"] == 0.5
    assert s["spurious_per_mutated_case"] == 0.0
    # clean [100, 80] vs material [92, 100]: 100>92, 100=100 (half), 80<92, 80<100
    assert s["score_auc_clean_vs_material"] == 0.375
    assert s["error_rate"] == rate(1, 7)
    assert s["grades"]["clean"] == {"pass": 1, "warning": 1, "fail": 0}
    rows = {row["mutator"]: row for row in s["by_mutator"]}
    assert (rows["none"]["n"], rows["none"]["alarms"], rows["none"]["mean_score"]) == (2, 1, 90.0)
    assert "delete_table" not in rows


def test_fix_success_needs_a_clean_recheck_kept_values_and_restored_text():
    good = {"recheck_clean": True, "values_kept": True, "text_restored": True,
            "style_restored": False}
    blind = {"recheck_clean": True, "values_kept": True, "text_restored": False,
             "style_restored": False}
    records = [
        record("delete_clause", material=True, targets=("c",), kind="missing_fixed",
               fixable=True, fix=good, diffs=(("missing_fixed", "error", "c"),)),
        record("change_liability_cap", material=True, targets=("c",), kind="changed_fixed",
               fixable=True, fix=blind),
        record("heading_caps", material=False, targets=("h",), kind="changed_fixed",
               fixable=True, fix=good),  # benign: not part of fix success
    ]
    s = summarize(records)
    assert s["fix_success"] == rate(1, 2)
    assert s["fix_recheck_clean"] == rate(2, 2)  # a re-check can't see what the check missed
    assert s["fix_text_restored"] == rate(1, 2)
    assert s["fix_style_restored"] == rate(0, 2)


def test_a_mutator_with_mixed_materiality_gets_one_row_per_materiality():
    records = [
        record("delete_clause", material=True, targets=("c",), kind="missing_fixed",
               diffs=(("missing_fixed", "error", "c"),), score=90.0),
        record("delete_clause", material=False, targets=("d",), kind="missing_fixed",
               diffs=(("missing_fixed", "error", "d"),), score=94.0),
    ]
    rows = sorted(summarize(records)["by_mutator"], key=lambda row: row["material"])
    assert [(row["material"], row["n"], row["mean_score"]) for row in rows] == [
        (False, 1, 94.0),
        (True, 1, 90.0),
    ]
