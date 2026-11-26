"""Rescoring recomputes outcomes from the recorded values, and only with the same notes."""

from __future__ import annotations

import pytest

from evals.corpus.notes import load_notes, notes_hash
from evals.metrics.generate import field_outcome
from evals.rescore import RescoreError, rescore

CASES = load_notes(["minutes_en"])
EMAIL = next(case for case in CASES if case.style == "email")
WRITTEN = "Anika Brandauer (chair), Samuel Rinaldi (minute taker), Lukas Novak, Mira Ostwald"


def _result(hash_=None):
    fields = {"field.attendees": {**field_outcome("names", WRITTEN, {"value": "x"}, "nothing"),
                                  "ai_drafted": False}}
    fields["field.attendees"]["outcome"] = "unsupported"  # as scored before the bracket rule
    record = {"id": EMAIL.id, "pair": EMAIL.pair, "style": EMAIL.style, "ai": True,
              "error": None, "fields": fields, "tables": {}, "free": {},
              "routing": {"source": "writer"}, "review": {"ran": True, "findings": 0},
              "layout": {"preserved": True}, "generate_ms": 10.0}
    return {"meta": {"suite": "generate", "notes_hash": hash_ or notes_hash(CASES)},
            "cases": [record], "repeats": []}


def test_rescoring_applies_todays_rules_to_the_recorded_values():
    result = rescore(_result(), {"git_sha": "abc", "dirty_code": False}, cases=CASES)
    field = result["cases"][0]["fields"]["field.attendees"]
    assert field["value"] == WRITTEN  # the value as recorded
    assert field["outcome"] == "grounded_wrong"  # every name is in the notes; the set differs
    assert result["aggregates"]["fields"]["hallucination_rate"]["num"] == 0
    assert result["meta"]["rescored"][-1]["outcomes_changed"] == 1
    assert result["meta"]["rescored"][-1]["git_sha"] == "abc"


def test_rescoring_refuses_other_notes_and_other_suites():
    with pytest.raises(RescoreError):
        rescore(_result(hash_="0" * 64), {}, cases=CASES)
    with pytest.raises(RescoreError):
        rescore({"meta": {"suite": "comply"}, "cases": []}, {}, cases=CASES)
