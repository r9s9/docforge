"""The CI gate on small hand-made results, and the committed thresholds against the committed
no-AI results."""

from __future__ import annotations

import copy
import os
import subprocess
import sys

import yaml

from evals import gate
from evals.metrics.comply import rate
from evals.metrics.comply import summarize as summarize_comply
from evals.paths import REPO_ROOT, THRESHOLDS_PATH

CORPUS = "c" * 64
CASES = ["nda_en/held_01/change_term", "nda_en/held_02/change_term", "nda_en/held_03/change_law"]


def _comply(found: set[str], *, corpus: str = CORPUS, ai: bool = False) -> dict:
    records = []
    for case_id in CASES:
        hit = case_id in found
        records.append({
            "id": case_id, "error": None, "score": 80.0 if hit else 100.0,
            "grade": "warning" if hit else "pass", "check_ms": 10.0, "extras": [],
            "label": {"mutator": "change_term", "targets": ["clause.term"], "material": True,
                      "expected_kind": "changed_fixed", "fixable": False},
            "differences": [{"logical_id": "clause.term", "kind": "changed_fixed",
                             "severity": "warning"}] if hit else [],
        })
    meta = {"suite": "comply", "config": "haiku" if ai else "no-ai", "corpus_hash": corpus,
            "ai": {"enabled": ai}}
    return {"meta": meta, "aggregates": summarize_comply(records), "cases": records}


def _generate(right: int, hallucinated: int) -> dict:
    return {"meta": {"suite": "generate", "config": "no-ai", "corpus_hash": CORPUS,
                     "notes_hash": "n" * 64, "ai": {"enabled": False}},
            "aggregates": {"fields": {"accuracy": rate(right, 10),
                                      "hallucination_rate": rate(hallucinated, 10)},
                           "error_rate": rate(0, 5)},
            "cases": []}


def _analyze(f1_k1: float) -> dict:
    by_k = {k: {"field_f1": {"value": f1_k1 if k == "1" else 0.9, "tp": 9, "fp": 1, "fn": 1}}
            for k in gate.KS}
    return {"meta": {"suite": "analyze", "config": "no-ai", "corpus_hash": CORPUS,
                     "analyze_hash": "a" * 64, "ai": {"enabled": False}},
            "aggregates": {"by_k": by_k, "error_rate": rate(0, 45)}, "cases": []}


def _baseline() -> dict:
    return {"comply": _comply({CASES[0], CASES[1]}), "generate": _generate(4, 0),
            "analyze": _analyze(0.68)}


NAMES = {"comply": "c.json", "generate": "g.json", "analyze": "a.json"}


def test_measure_keeps_counts_and_marks_what_a_result_lacks():
    now = gate.measure(_generate(4, 1))
    assert now["fields_right"] == {"value": 0.4, "num": 4, "den": 10}
    assert now["layout_kept"] is None  # this small result has no pipeline numbers
    assert gate.measure(_analyze(0.7))["field_f1_k1"] == {"value": 0.7, "tp": 9, "fp": 1,
                                                          "fn": 1}


def test_a_run_at_the_baseline_passes():
    thresholds = gate.thresholds_from(_baseline(), NAMES)
    assert thresholds["comply"]["detected"] == sorted([CASES[0], CASES[1]])
    report = gate.check(thresholds, _baseline())
    assert report["passed"] and not report["lost"] and not report["improved"]


def test_a_lost_detection_fails_and_is_named():
    thresholds = gate.thresholds_from(_baseline(), NAMES)
    results = {**_baseline(), "comply": _comply({CASES[0]})}
    report = gate.check(thresholds, results)
    assert not report["passed"] and report["lost"] == [CASES[1]]
    row = next(r for r in report["rows"] if r["check"] == "deviations found before, still found")
    assert (row["now"], row["status"], row["note"]) == ("1/2", "FAIL", "1 lost")
    text = gate.render(report, "thresholds.yaml")
    assert CASES[1] in text and "FAILED" in text


def test_a_drop_fails_in_either_direction():
    thresholds = gate.thresholds_from(_baseline(), NAMES)
    worse = {**_baseline(), "generate": _generate(4, 1), "analyze": _analyze(0.60)}
    report = gate.check(thresholds, worse)
    failed = {r["check"] for r in report["rows"] if r["status"] == "FAIL"}
    assert failed == {"hallucinated", "field F1, 1 example"}  # a ceiling rose, a floor fell


def test_an_improvement_passes_with_a_note_to_raise_the_thresholds():
    thresholds = gate.thresholds_from(_baseline(), NAMES)
    better = {**_baseline(), "comply": _comply(set(CASES)), "analyze": _analyze(0.75)}
    report = gate.check(thresholds, better)
    assert report["passed"] and report["improved"] and report["gained"] == [CASES[2]]
    assert "gate --update" in gate.render(report, "thresholds.yaml")


def test_other_cases_an_ai_result_or_a_missing_suite_fail():
    thresholds = gate.thresholds_from(_baseline(), NAMES)
    other = gate.check(thresholds, {**_baseline(), "comply": _comply({CASES[0], CASES[1]},
                                                                      corpus="d" * 64)})
    assert not other["passed"] and "corpus_hash" in other["problems"][0]
    ai = gate.check(thresholds, {**_baseline(), "comply": _comply({CASES[0]}, ai=True)})
    assert not ai["passed"] and "no-AI results" in ai["problems"][0]
    missing = {k: v for k, v in _baseline().items() if k != "generate"}
    assert gate.check(thresholds, missing)["problems"] == ["generate: no result given"]


def test_the_thresholds_file_reads_back_as_written():
    content = gate.thresholds_from(_baseline(), NAMES)
    text = gate.to_yaml(content)
    assert text.startswith("# The CI gate's thresholds")
    assert yaml.safe_load(text) == copy.deepcopy(content)


def test_the_committed_thresholds_are_the_committed_no_ai_results_and_they_pass(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    written = tmp_path / "thresholds.yaml"

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "evals", "gate", *args], cwd=REPO_ROOT,
                              env=env, capture_output=True, text=True, timeout=120)

    update = cli("--update", "--thresholds", str(written))
    assert update.returncode == 0, update.stderr
    assert written.read_text(encoding="utf-8") == THRESHOLDS_PATH.read_text(encoding="utf-8"), (
        "evals/thresholds.yaml is stale: run `python -m evals gate --update`")
    done = cli()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PASSED" in done.stdout
