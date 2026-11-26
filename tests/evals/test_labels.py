"""The grader-agreement check: which items the owner labels, and how agreement is counted."""

from __future__ import annotations

from evals.graders.labels import agreement, graded_items, sheet
from evals.metrics.comply import rate

CASES = ["service_agreement_en/bullets", "service_agreement_en/email", "nda_en/bullets",
         "nda_en/email", "minutes_en/bullets", "minutes_en/email"]


def _result(config, verdicts):
    """A generate result whose graded free text has the given (faithful, complete) verdicts."""
    cases = []
    for case_id, (faithful, complete) in zip(CASES, verdicts, strict=False):
        field = "text.services" if "service" in case_id else (
            "field.purpose" if "nda" in case_id else "text.agenda")
        cases.append({"id": case_id, "free": {field: {
            "value": f"{config} value for {case_id}", "points": ["a point"],
            "grade": {"status": "graded", "faithful": faithful, "complete": complete}}}})
    cases.append({"id": "nda_de/bullets", "free": {"field.purpose": {
        "value": "x", "points": None, "grade": {"status": "failed"}}}})  # not graded: skipped
    return {"meta": {"config": config}, "cases": cases}


def test_only_graded_values_are_items():
    items = graded_items(_result("haiku", [(True, True)] * 6))
    assert len(items) == 6 and {i["config"] for i in items} == {"haiku"}


def test_the_sheet_takes_half_its_items_from_no_answers_and_hides_the_verdicts():
    verdicts = [(True, True), (False, True), (True, False), (True, True), (True, True),
                (True, True)]
    data = sheet([_result("haiku", verdicts), _result("local", verdicts)], per_mode=4)
    assert data["results"] == ["haiku", "local"] and len(data["items"]) == 8
    for config in ("haiku", "local"):
        mine = [i for i in data["items"] if i["source"]["config"] == config]
        said_no = [i for i in mine if i["source"]["case"] in CASES[1:3]]
        assert len(mine) == 4 and len(said_no) == 2  # both "no" items, then two "yes" ones
    item = data["items"][0]
    assert set(item) == {"id", "source", "document", "field", "notes", "points", "value"}
    assert "grade" not in str(item)  # the owner labels blind
    assert sheet([_result("haiku", verdicts), _result("local", verdicts)], per_mode=4) == data


def test_with_too_few_yes_answers_the_sheet_takes_more_no_answers():
    data = sheet([_result("local", [(False, False)] * 5 + [(True, True)])], per_mode=4)
    assert len(data["items"]) == 4


def test_agreement_per_question_and_the_gate():
    results = [_result("haiku", [(True, True), (False, True), (True, False), (True, None)])]
    data = sheet(results, per_mode=4)
    by_case = {i["source"]["case"]: i["id"] for i in data["items"]}
    owner = {"labels": {
        by_case[CASES[0]]: {"faithful": True, "complete": True},    # agrees twice
        by_case[CASES[1]]: {"faithful": True, "complete": True},    # faithful disagrees
        by_case[CASES[2]]: {"faithful": True, "complete": False},   # agrees twice
        by_case[CASES[3]]: {"faithful": True, "complete": True},    # grader didn't ask complete
    }}
    result = agreement(data, owner, results)
    assert result["faithful"]["agreement"] == rate(3, 4)
    assert result["faithful"]["used"] is False  # 0.75 is below the 0.85 gate
    assert result["faithful"]["disagreements"] == [
        {"item": by_case[CASES[1]], "owner": True, "grader": False}]
    assert result["complete"]["agreement"] == rate(3, 3) and result["complete"]["used"] is True
    unlabelled = agreement(data, {"labels": {}}, results)
    assert unlabelled["faithful"]["agreement"] == rate(0, 0)
    assert unlabelled["faithful"]["used"] is False


def test_a_mode_with_too_few_graded_values_gives_its_share_to_the_others():
    few = _result("no-ai", [(True, True)] * 2)  # only 2 graded values
    data = sheet([few, _result("haiku", [(True, True)] * 6), _result("local", [(True, True)] * 6)],
                 per_mode=4)
    counts = {c: sum(i["source"]["config"] == c for i in data["items"])
              for c in ("no-ai", "haiku", "local")}
    assert counts == {"no-ai": 2, "haiku": 5, "local": 5} and len(data["items"]) == 12
