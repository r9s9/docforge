"""``python -m evals compare``: the side-by-side table and the cases whose alarm changed.

The results are tiny, made by hand, and summarized with the real metric code. Four cases:
- ``a``: a material deviation, flagged error. Every judge calls it material.
- ``b``: a benign change, flagged warning. Haiku downgrades it to info.
- ``c``: a clean control. Nothing to judge, except in the local run, where a spurious
  difference is raised to warning.
- ``d``: a material deviation, flagged warning. Haiku downgrades it to info.
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from evals import compare
from evals.cli import main
from evals.metrics.comply import summarize

CORPUS = "c" * 64


def case(case_id, mutator, *, material=False, target=None, severity=None, verdict=None,
         status=None, spend=0.0, unpriced=0, score=100.0, error=None):
    """One case record with at most one difference (on ``target``, or elsewhere if None)."""
    differences = []
    if severity:
        difference = {"kind": "changed_fixed", "severity": severity,
                      "logical_id": target or "elsewhere"}
        if verdict is not None:
            difference["verdict"] = {"material": verdict, "severity": severity}
        differences.append(difference)
    record = {
        "id": case_id,
        "label": {"mutator": mutator, "targets": [target] if target else [],
                  "expected_kind": "changed_fixed" if target else None, "material": material,
                  "rule_dependent": False, "fixable": False, "detail": {}},
        "differences": differences, "extras": [], "score": score, "grade": "pass",
        "fix": None, "error": error, "check_ms": 10.0,
    }
    if status:
        record["judge"] = {"status": status}
        record["dimensions"] = {"semantic": 50.0} if status == "ran" else {}
        record["spend_usd"] = {"live": spend, "replayed": 0.0, "unpriced_calls": unpriced}
        record["ai_calls"] = []
    return record


def result(config, records, *, model=None, corpus=CORPUS, rebuilt=False):
    meta = {"config": config, "corpus_hash": corpus,
            "ai": {"enabled": True, "model": model} if model else {"enabled": False},
            "corpus": {"corpus_hash": corpus, "files_match_manifest": not rebuilt}}
    return {"meta": meta, "aggregates": summarize(records), "cases": records}


def no_ai():
    return result("no-ai", [
        case("a", "delete_clause", material=True, target="c1", severity="error", score=60.0),
        case("b", "heading_caps", target="h1", severity="warning", score=90.0),
        case("c", "none"),
        case("d", "change_cap", material=True, target="c2", severity="warning", score=80.0),
    ])


def haiku():
    return result("haiku", [
        case("a", "delete_clause", material=True, target="c1", severity="error", verdict=True,
             status="ran", spend=0.002, score=60.0),
        case("b", "heading_caps", target="h1", severity="info", verdict=False, status="ran",
             spend=0.001, score=90.0),
        case("c", "none", status="not_needed"),
        case("d", "change_cap", material=True, target="c2", severity="info", verdict=False,
             status="ran", spend=0.001, score=80.0),
    ], model="claude-haiku-5-5")


def local():
    return result("local", [
        case("a", "delete_clause", material=True, target="c1", severity="error", verdict=True,
             status="ran", unpriced=1, score=60.0),
        case("b", "heading_caps", target="h1", severity="warning", verdict=True, status="ran",
             unpriced=1, score=90.0),
        case("c", "none", severity="warning", verdict=True, status="ran", unpriced=1),
        case("d", "change_cap", material=True, status="failed", error="TimeoutError: slow"),
    ], model="qwen3.6-27b", rebuilt=True)


def markdown_rows(results):
    lines = compare.table(results, markdown=True).splitlines()
    cells = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    return cells[0], {row[0]: row[1:] for row in cells[2:]}


def test_the_table_has_one_column_per_result_and_says_what_a_mode_does_not_measure():
    header, rows = markdown_rows([no_ai(), haiku(), local()])
    assert header == ["metric", "no-ai", "haiku (claude-haiku-5-5)", "local (qwen3.6-27b)"]
    assert [label for label, _render in compare.ROWS] == list(rows)
    assert rows["material deviations found"] == ["1.00 (2/2)", "1.00 (2/2)", "1.00 (1/1)"]
    assert rows["material still alarming"] == ["1.00 (2/2)", "0.50 (1/2)", "1.00 (1/1)"]
    assert rows["benign changes that alarm"] == ["1.00 (1/1)", "0.00 (0/1)", "1.00 (1/1)"]
    assert rows["clean controls that alarm"] == ["0.00 (0/1)", "0.00 (0/1)", "1.00 (1/1)"]
    # Haiku: a is TP, b is TN, d is FN. Local: a is TP, b and c are FP; d errored.
    assert rows["judge: material precision"] == ["n/a", "1.00 (1/1)", "0.33 (1/3)"]
    assert rows["judge: material recall"] == ["n/a", "0.50 (1/2)", "1.00 (1/1)"]
    assert rows["judge: accuracy"] == ["n/a", "0.67 (2/3)", "0.33 (1/3)"]
    assert rows["judge fell back"] == ["n/a", "0.00 (0/3)", "0.00 (0/3)"]
    assert rows["judge stable across repeats"] == ["n/a", "n/a", "n/a"]  # no repeats here
    assert rows["score AUC clean > material"] == ["1.00", "1.00", "1.00"]
    # Haiku: clean c had nothing to judge (100) > a and d (50). Local: c and a tie at 50.
    assert rows["semantic AUC clean > material"] == ["n/a", "1.00", "0.50"]
    assert rows["cost per document"] == ["$0 (no AI)", "$0.0010", "$0 (hardware)"]
    assert rows["cost per judged document"] == ["$0 (no AI)", "$0.0013", "$0 (hardware)"]
    assert rows["total cost, repeats included"] == ["$0 (no AI)", "$0.0040", "$0 (hardware)"]
    assert rows["check latency p50 / p95, all cases"][0] == "10.00 / 10.00 ms"
    assert rows["errors"] == ["0.00 (0/4)", "0.00 (0/4)", "0.25 (1/4)"]
    assert rows["run on"] == ["n/a", "n/a", "n/a"]


def test_total_cost_includes_the_repeats_and_latency_can_be_limited_to_judged_cases():
    run = haiku()
    run["meta"].update(spend_usd={"live": 0.005, "replayed": 0.001}, platform="Windows",
                       python="3.13.17")
    for record, ms in zip(run["cases"], (100.0, 300.0, 5.0, 200.0), strict=True):
        record["check_ms"] = ms
    _header, rows = markdown_rows([run])
    assert rows["total cost, repeats included"] == ["$0.0060"]  # the per-pass total is $0.0040
    # Cases with differences: 100, 200 and 300 ms; p95 is at position 1.9 of 0..2.
    assert rows["check latency p50 / p95, cases with differences"] == ["200.00 / 290.00 ms"]
    assert rows["run on"] == ["Windows, Python 3.13.17"]


def test_the_plain_table_lines_every_value_up_under_its_column():
    results = [no_ai(), haiku()]
    lines = compare.table(results).splitlines()
    starts = [lines[0].index(name) for name in ("no-ai", "haiku (claude-haiku-5-5)")]
    assert len(lines) == 1 + len(compare.ROWS)
    for line, (label, _render) in zip(lines[1:], compare.ROWS, strict=True):
        assert line.startswith(label)
        for start in starts:
            assert line[start - 1] == " " and line[start] != " ", line


def test_the_corpus_note_warns_about_different_corpora_and_names_local_rebuilds():
    assert compare.corpus_note([no_ai(), haiku()]) == (
        "Same corpus (cccccccccccc) in every result.")
    assert compare.corpus_note([no_ai(), local()]) == (
        "Same corpus (cccccccccccc) in every result. local rebuilt the files locally with "
        "other library versions (same ground truth and labels).")
    other = result("haiku", haiku()["cases"], model="claude-haiku-5-5", corpus="d" * 64)
    assert compare.corpus_note([no_ai(), other]).startswith("WARNING")


def test_flips_list_the_alarms_the_judge_removed_or_added_and_skip_errored_cases():
    assert compare.flips(no_ai(), haiku()) == {
        "benign: alarm removed": ["b"],
        "material: alarm removed": ["d"],
    }
    assert compare.flips(no_ai(), local()) == {"clean: alarm added": ["c"]}  # d errored
    assert compare.flips(no_ai(), no_ai()) == {}


def test_the_report_puts_the_note_the_table_and_the_flips_together():
    text = compare.report([no_ai(), haiku(), no_ai()], show=1)
    assert text.splitlines()[0] == "Same corpus (cccccccccccc) in every result."
    assert "Alarm changes, no-ai → haiku (claude-haiku-5-5):" in text
    assert "  material: alarm removed: 1 — d" in text
    assert "Alarm changes, no-ai → no-ai:\n  none" in text

    base = no_ai()
    more = result("haiku", [case(f"x{i}", "heading_caps", target="h", severity="warning")
                            for i in range(3)])
    quiet = result("local", [case(f"x{i}", "heading_caps", target="h", severity="info",
                                  verdict=False, status="ran") for i in range(3)], model="m")
    base["cases"] += more["cases"]
    assert "  benign: alarm removed: 3 — x0 … and 2 more" in compare.report([base, quiet],
                                                                             show=1)


def test_compare_command_reads_result_files(tmp_path, capsys):
    paths = []
    for name, made in (("no-ai", no_ai()), ("haiku", haiku())):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(made), encoding="utf-8")
        paths.append(str(path))
    assert main(["compare", *paths, "--markdown"]) == 0
    out = capsys.readouterr().out
    assert "| metric | no-ai | haiku (claude-haiku-5-5) |" in out
    assert "material: alarm removed: 1 — d" in out

    assert main(["compare", paths[0]]) == 2
    assert "two or more" in capsys.readouterr().err


def test_output_that_cannot_show_an_arrow_gets_a_question_mark_instead_of_a_crash(
        tmp_path, monkeypatch):
    paths = []
    for name, made in (("no-ai", no_ai()), ("haiku", haiku())):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(made), encoding="utf-8")
        paths.append(str(path))
    redirected = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")  # Windows, piped to a file
    monkeypatch.setattr(sys, "stdout", redirected)
    assert main(["compare", *paths]) == 0
    redirected.flush()
    assert b"Alarm changes, no-ai ? haiku" in redirected.buffer.getvalue()


def _generated(config, outcomes, *, notes="n" * 64, faithful=None):
    from evals.metrics.generate import summarize as summarize_generate

    records = []
    for case_id, outcome in outcomes.items():
        free = {}
        if faithful is not None:
            free["text.services"] = {"value": "v", "points": ["p"], "grade": {
                "status": "graded", "faithful": faithful, "complete": True}}
        records.append({
            "id": case_id, "style": "bullets", "ai": False, "error": None, "generate_ms": 50.0,
            "fields": {"field.date": {"kind": "date", "expected": "x",
                                      "value": None if outcome == "omitted" else "x",
                                      "outcome": outcome, "ai_drafted": False,
                                      "placeholder": False, "superseded": False,
                                      "form_kept": None}},
            "tables": {}, "free": free, "routing": {"source": "heuristic"},
            "review": {"ran": False}, "layout": {"preserved": True},
        })
    return {"meta": {"config": config, "suite": "generate", "corpus_hash": CORPUS,
                     "notes_hash": notes, "ai": {"enabled": False}},
            "aggregates": summarize_generate(records), "cases": records}


def test_generate_results_get_their_own_rows_and_field_outcome_changes():
    no_ai = _generated("no-ai", {"a": "omitted", "b": "correct"}, faithful=True)
    haiku = _generated("haiku", {"a": "correct", "b": "unsupported"}, faithful=False)
    header, rows = markdown_rows([no_ai, haiku])
    assert rows["short fields right"] == ["0.50 (1/2)", "0.50 (1/2)"]
    assert rows["hallucinated"] == ["0.00 (0/1)", "0.50 (1/2)"]
    assert rows["free text faithful"] == ["1.00 (2/2)", "0.00 (0/2)"]
    assert rows["written by"] == ["heuristic 2", "heuristic 2"]
    assert compare.outcome_changes(no_ai, haiku) == {
        "correct → unsupported": ["b field.date"], "omitted → correct": ["a field.date"]}
    text = compare.report([no_ai, haiku])
    assert "Field outcome changes, no-ai → haiku:" in text


def test_grades_a_disagreeing_grader_gave_are_not_reported():
    no_ai = _generated("no-ai", {"a": "correct"}, faithful=True)
    agreement = {"faithful": {"used": False}, "complete": {"used": True}}
    _header, rows = markdown_rows([no_ai, no_ai])  # without an agreement file: the grades
    assert rows["free text faithful"] == ["1.00 (1/1)", "1.00 (1/1)"]
    lines = compare.table([no_ai, no_ai], markdown=True, agreement=agreement).splitlines()
    faithful = next(line for line in lines if line.startswith("| free text faithful"))
    assert "not graded (grader disagrees with the owner)" in faithful


def test_results_of_different_suites_or_notes_are_flagged():
    generated = _generated("no-ai", {"a": "correct"})
    with pytest.raises(ValueError):
        compare.table([no_ai(), generated])
    other_notes = _generated("haiku", {"a": "correct"}, notes="m" * 64)
    assert compare.corpus_note([generated, other_notes]).startswith(
        "WARNING: these results were run on different notes cases")


def _analyzed(config, clause_outcome, *, k=1, analyze="a" * 64):
    from evals.metrics.analyze import summarize as summarize_analyze

    records = [{
        "id": f"invoice_en/k{k}", "pair": "invoice_en", "lang": "en", "k": k,
        "group": "examples", "ai": False, "error": None, "analyze_ms": 80.0,
        "source": "heuristic", "layout": {"preserved": True},
        "outcomes": {
            "clause.payment": {"kind": "fixed", "outcome": clause_outcome},
            "field.total": {"kind": "field", "field_type": "money", "outcome": "found",
                            "type_ok": True},
        },
    }]
    return {"meta": {"config": config, "suite": "analyze", "corpus_hash": CORPUS,
                     "analyze_hash": analyze, "ai": {"enabled": False}},
            "aggregates": summarize_analyze(records), "cases": records}


def test_analyze_results_get_a_row_per_metric_and_number_of_examples():
    before = _analyzed("no-ai", "became_field")
    after = _analyzed("haiku", "kept")
    _header, rows = markdown_rows([before, after])
    assert rows["field F1, 1 example"] == ["0.67 (tp 1 · fp 1 · fn 0)",
                                           "1.00 (tp 1 · fp 0 · fn 0)"]
    assert rows["boilerplate kept, 1 example"] == ["0.00 (0/1)", "1.00 (1/1)"]
    assert rows["field F1, 2 examples"] == ["n/a", "n/a"]  # no case with 2 examples
    assert rows["amounts typed as numbers"] == ["1.00 (1/1)", "1.00 (1/1)"]
    assert rows["classified by"] == ["heuristic 1", "heuristic 1"]
    assert compare.element_changes(before, after) == {
        "fixed became_field → kept": ["invoice_en/k1 clause.payment"]}
    assert "Element outcome changes, no-ai → haiku:" in compare.report([before, after])


def test_analyze_results_on_different_documents_are_flagged():
    note = compare.corpus_note([_analyzed("no-ai", "kept"),
                                _analyzed("haiku", "kept", analyze="b" * 64)])
    assert note.startswith("WARNING: these results were run on different analyze documents")
