"""Recompute a generate result's outcomes from the values it recorded, with today's metric code.

A generate run records every value DocForge wrote, so when a comparison rule improves (a role in
brackets is not part of a name, "11 Stunden" is the quantity 11), the outcomes can be computed
again without generating, or paying for, anything again. What the run measured directly stays
as recorded: the values, the grader's verdicts, the layout check, timings and cost.

The result keeps a note of when and with which code it was rescored. The notes cases must be the
ones the run used (the same ``notes_hash``); otherwise rescoring would compare against other
expected values, and it refuses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evals.corpus.doc_types import SPECS
from evals.corpus.notes import NotesCase, field_kinds, load_notes, notes_hash
from evals.metrics.generate import field_outcome, summarize, table_outcome


class RescoreError(ValueError):
    """A result that can't be rescored with the notes cases at hand."""


def _rescore_record(record: dict[str, Any], case: NotesCase) -> int:
    changed = 0
    kinds = field_kinds(case.pair)
    lang = SPECS[case.pair].lang
    for logical, field in (record.get("fields") or {}).items():
        again = field_outcome(
            kinds[logical], field["value"], case.expected[logical], case.text,
            superseded=case.superseded.get(logical), ai_drafted=field["ai_drafted"], lang=lang,
        )
        changed += again["outcome"] != field["outcome"]
        record["fields"][logical] = again
    for logical, table in (record.get("tables") or {}).items():
        rows = table["rows"]
        record["tables"][logical] = {**table_outcome(case.expected[logical], rows, case.text),
                                     "rows": rows}
    return changed


def rescore(result: dict[str, Any], git: dict[str, Any],
            cases: list[NotesCase] | None = None) -> dict[str, Any]:
    """The result with its outcomes and aggregates recomputed; changes it in place."""
    if result["meta"].get("suite") != "generate":
        raise RescoreError("only generate results record the values needed to rescore")
    cases = cases if cases is not None else load_notes()
    if notes_hash(cases) != result["meta"].get("notes_hash"):
        raise RescoreError("the notes cases changed since this run; rescoring would compare "
                           "against other expected values")
    by_id = {case.id: case for case in cases}
    changed = 0
    for record in result["cases"] + (result.get("repeats") or []):
        if not record.get("error"):
            changed += _rescore_record(record, by_id[record["id"]])
    result["aggregates"] = summarize(result["cases"], result.get("repeats") or [])
    result["meta"].setdefault("rescored", []).append({
        "date": datetime.now(UTC).date().isoformat(),
        "git_sha": git.get("git_sha"),
        "dirty_code": git.get("dirty_code"),
        "outcomes_changed": changed,
    })
    return result
