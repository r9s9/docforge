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


# --- AI modes --------------------------------------------------------------------------------

from evals.metrics.comply import (  # noqa: E402
    ai_call_failures,
    cost_summary,
    judge_matrix,
    material_alarms_kept,
    semantic_score,
    stability,
)


def judged(mutator, *, material, targets=(), diffs=(), status="ran", semantic=None,
           spend=None, calls=(), case_id="x"):
    """A record from an AI run: diffs are (kind, severity, logical_id, verdict material|None)."""
    r = record(mutator, material=material, targets=targets)
    r["id"] = case_id
    r["differences"] = [
        {"kind": k, "severity": s, "logical_id": lid,
         **({"verdict": {"material": v, "severity": s}} if v is not None else {})}
        for k, s, lid, v in diffs
    ]
    r["judge"] = {"status": status}
    r["dimensions"] = {"semantic": semantic} if semantic is not None else {}
    r["spend_usd"] = spend or {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
    r["ai_calls"] = [{"kind": kind, "outcome": outcome} for kind, outcome in calls]
    return r


def test_judge_matrix_scores_verdicts_against_the_deviation_labels():
    records = [
        # material deviation called material: TP; a spurious difference called benign: TN
        judged("change_liability_cap", material=True, targets=("c",),
               diffs=(("changed_fixed", "error", "c", True),
                      ("missing_fixed", "info", "z", False))),
        # benign change called material: FP
        judged("heading_caps", material=False, targets=("h",),
               diffs=(("changed_fixed", "error", "h", True),)),
        # material deviation called benign: FN; one difference never judged
        judged("delete_clause", material=True, targets=("d",),
               diffs=(("missing_fixed", "info", "d", False),
                      ("missing_fixed", "error", "d", None))),
        # judge failed: not counted
        judged("delete_table", material=True, targets=("t",), status="failed",
               diffs=(("missing_table", "error", "t", None),)),
    ]
    m = judge_matrix(records)
    assert (m["tp"], m["fp"], m["fn"], m["tn"], m["not_judged"]) == (1, 1, 1, 1, 1)
    assert m["precision"] == rate(1, 2) and m["recall"] == rate(1, 2)
    assert m["accuracy"] == rate(2, 4)


def test_semantic_score_is_100_with_nothing_to_judge_and_absent_when_the_judge_failed():
    assert semantic_score(judged("x", material=False, semantic=50.0)) == 50.0
    assert semantic_score(judged("none", material=False, status="not_needed")) == 100.0
    assert semantic_score(judged("x", material=True, status="failed")) is None


def test_material_alarms_kept_counts_downgrades_by_the_judge():
    kept = judged("delete_clause", material=True, targets=("d",),
                  diffs=(("missing_fixed", "error", "d", True),))
    downgraded = judged("empty_field", material=True, targets=("f",),
                        diffs=(("missing_field", "info", "f", False),))
    missed = judged("remove_row", material=True, targets=("t",))
    assert material_alarms_kept([kept, downgraded, missed]) == rate(1, 2)


def test_cost_summary_per_document_and_per_judged_document():
    records = [
        judged("a", material=True, spend={"live": 0.002, "replayed": 0.0, "unpriced_calls": 0}),
        judged("b", material=True, spend={"live": 0.0, "replayed": 0.004, "unpriced_calls": 0}),
        judged("none", material=False, status="not_needed"),
    ]
    cost = cost_summary(records)
    assert cost["total"] == pytest.approx(0.006) and cost["live"] == pytest.approx(0.002)
    assert cost["per_document"] == pytest.approx(0.002)
    assert cost["per_judged_document"] == pytest.approx(0.003)


def test_ai_call_failures_by_kind():
    records = [
        judged("a", material=True, calls=(("LLMComplianceJudgement", "ok"),)),
        judged("b", material=True, calls=(("LLMComplianceJudgement", "error"),)),
    ]
    assert ai_call_failures(records) == {"LLMComplianceJudgement": rate(1, 2)}


def test_stability_compares_verdicts_and_semantic_scores_across_repeats():
    base = judged("x", material=True, targets=("c",), semantic=50.0, case_id="case-1",
                  diffs=(("changed_fixed", "error", "c", True),
                         ("missing_fixed", "info", "z", False)))
    repeats = [
        {"id": "case-1", "repeat": 1, "error": None, "semantic": 50.0,
         "verdicts": [{"material": True}, {"material": False}]},
        {"id": "case-1", "repeat": 2, "error": None, "semantic": 100.0,
         "verdicts": [{"material": False}, {"material": False}]},
    ]
    s = stability([base], repeats)
    assert s["cases"] == 1 and s["runs_per_case"] == 3
    assert s["verdict_agreement"] == rate(1, 2)  # difference 0 flipped once, 1 never did
    assert s["semantic_spread_mean"] == 50.0
    assert stability([base], []) is None


def test_an_ai_run_has_no_fix_numbers_and_has_an_ai_section():
    records = [judged("delete_clause", material=True, targets=("d",),
                      diffs=(("missing_fixed", "error", "d", True),), semantic=0.0)]
    records[0]["label"]["fixable"] = True
    s = summarize(records)
    assert s["fix_success"]["den"] == 0 and s["fix_success"]["value"] is None
    assert s["ai"]["judge"]["tp"] == 1
