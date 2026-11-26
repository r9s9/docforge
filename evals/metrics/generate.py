"""Generate metrics (DESIGN.md §5.2): what DocForge wrote from a notes text, against the notes.

A **field outcome** is one of, tested in this order:
- ``correct``: equals the expected value, or an accepted form of it
- ``correctly_empty``: empty, and the notes don't give the value
- ``omitted``: empty, but the notes give the value
- ``grounded_wrong``: wrong, but the value is in the notes (another field's value, or a value the
  notes later correct)
- ``unsupported``: wrong, and in no form in the notes. **A hallucination.**

A placeholder ("TBD", "[Start Date]") counts as empty: it states nothing. A hallucination the
writer marked ``ai_drafted`` is **flagged** (the app shows it for review); otherwise it is
**silent**.

Rates carry their counts, as in the comply metrics. Records that errored count only in the
error rate. These are pure functions: plain data in, numbers out.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from evals.corpus.values import fmt_date, fmt_money
from evals.metrics.comply import percentile, rate
from evals.metrics.normalize import (
    appears_in,
    appears_in_cell,
    is_empty,
    is_placeholder,
    norm_text,
    parse_date,
    parse_money,
    same,
    same_cell,
)

OUTCOMES = ("correct", "correctly_empty", "omitted", "grounded_wrong", "unsupported")


def _blank(value: Any) -> bool:
    return is_empty(value) or is_placeholder(value)


def form_kept(kind: str, value: Any, lang: str) -> bool | None:
    """Whether a date or amount is written the way the template writes it (None: not a date or
    amount, or not parseable)."""
    if kind == "date":
        parsed = parse_date(value)
        return None if parsed is None else str(value).strip() == fmt_date(parsed, lang)
    if kind == "money":
        cents = parse_money(value)
        return None if cents is None else str(value).strip() == fmt_money(cents, lang)
    return None


def field_outcome(kind: str, value: Any, expectation: dict[str, Any], notes: str, *,
                  superseded: str | None = None, ai_drafted: bool = False,
                  lang: str = "en") -> dict[str, Any]:
    """The outcome of one short field, with what explains it."""
    expected, accept = expectation.get("value"), expectation.get("accept") or []
    right = [v for v in [expected, *accept] if v is not None]
    if not _blank(value) and any(same(kind, value, r) for r in right):
        outcome = "correct"
    elif _blank(value):
        outcome = "correctly_empty" if expected is None else "omitted"
    elif appears_in(kind, value, notes):
        outcome = "grounded_wrong"
    else:
        outcome = "unsupported"
    return {
        "kind": kind,
        "value": value,
        "expected": expected,
        "outcome": outcome,
        "ai_drafted": bool(ai_drafted),
        "placeholder": is_placeholder(value),
        "superseded": bool(superseded) and not _blank(value) and same(kind, value, superseded),
        "form_kept": form_kept(kind, value, lang) if outcome == "correct" else None,
    }


def _row_score(row: list[Any], expected: list[list[str] | None], columns: tuple[str, ...]) -> int:
    """How well a written row fits an expected row: matching cells, the first one counting
    double, because it names the row."""
    score = 0
    for c, (cell, alternatives, kind) in enumerate(zip(row, expected, columns, strict=False)):
        if alternatives and any(same_cell(kind, cell, alt) for alt in alternatives):
            score += 2 if c == 0 else 1
    return score


def table_outcome(expectation: dict[str, Any], rows: list[list[Any]] | None,
                  notes: str) -> dict[str, Any]:
    """Rows and cells of one table against the expected rows.

    Written rows are matched to expected rows greedily, best match first (the first column
    counts double), so a reordered table still scores its cells. A written cell that matches
    no expected cell and isn't in the notes is **unsupported**.
    """
    columns = tuple(expectation.get("columns") or ())
    expected_rows = expectation.get("rows")
    written = [list(r) for r in (rows or []) if any(not _blank(c) for c in r)]
    result: dict[str, Any] = {
        "rows_expected": None if expected_rows is None else len(expected_rows),
        "rows_written": len(written),
        "row_count_ok": None,
        "cells_expected": 0,
        "cells_correct": 0,
        "cells_written": sum(1 for r in written for c in r if not _blank(c)),
        "cells_unsupported": 0,
        "invented": False,
    }
    matched: dict[int, int] = {}  # expected row -> written row
    if expected_rows is not None:
        result["row_count_ok"] = len(written) == len(expected_rows)
        pairs = sorted(
            ((_row_score(w, e, columns), i, j) for i, e in enumerate(expected_rows)
             for j, w in enumerate(written)),
            key=lambda item: (-item[0], item[1], item[2]),
        )
        for score, i, j in pairs:
            if score > 0 and i not in matched and j not in matched.values():
                matched[i] = j
        for i, expected in enumerate(expected_rows):
            for c, (alternatives, kind) in enumerate(zip(expected, columns, strict=False)):
                if alternatives is None:
                    continue
                result["cells_expected"] += 1
                if i in matched:
                    cell = written[matched[i]][c] if c < len(written[matched[i]]) else None
                    if any(same_cell(kind, cell, alt) for alt in alternatives):
                        result["cells_correct"] += 1
    elif written:
        result["invented"] = True
    for j, row in enumerate(written):
        expected = None
        if expected_rows is not None:
            expected = next((expected_rows[i] for i, w in matched.items() if w == j), None)
        for c, cell in enumerate(row):
            if _blank(cell) or c >= len(columns):
                continue
            kind = columns[c]
            right = expected[c] if expected is not None and c < len(expected) else None
            if right and any(same_cell(kind, cell, alt) for alt in right):
                continue
            if not appears_in_cell(kind, cell, notes):
                result["cells_unsupported"] += 1
    return result


def layout_problems(truth: list[dict[str, Any]], template: list[tuple],
                    output: list[tuple]) -> list[str]:
    """What the output lost of the template's layout; empty when it kept all of it.

    ``truth`` is the representative document's ground truth, ``template`` its skeleton, and
    ``output`` the generated document's skeleton (``evals.corpus.ground_truth.skeleton``).
    Every fixed block must come back in order with the same text and style, every labelled
    field with its label and style, and every table with its header row. Extra paragraphs
    (multi-line prose) are allowed anywhere.
    """
    body = [item for item in output if item[0] == "body"]
    source = [item for item in template if item[0] == "body"]
    problems: list[str] = []
    position = 0
    for element in sorted((e for e in truth if e["locator"]["scope"] == "body"),
                          key=lambda e: e["locator"]["block"]):
        original = source[element["locator"]["block"]]
        if element["kind"] == "fixed":
            def wanted(item, original=original):
                return item[1:] == original[1:]
        elif element["kind"] == "field" and element.get("label"):
            prefix = norm_text(element["label"])

            def wanted(item, original=original, prefix=prefix):
                return (item[1] == "paragraph" and item[3] == original[3]
                        and norm_text(item[2]).startswith(prefix))
        elif element["kind"] == "table":
            header = original[2][0] if original[2] else ()

            def wanted(item, header=header):
                return item[1] == "table" and bool(item[2]) and tuple(item[2][0]) == tuple(header)
        else:
            continue  # free text may be empty or several paragraphs
        for j in range(position, len(body)):
            if wanted(body[j]):
                position = j + 1
                break
        else:
            problems.append(f"{element['id']}: missing or out of order")
    return problems


def _ok(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if not r.get("error")]


def _fields(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for r in records for f in (r.get("fields") or {}).values()]


def field_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The field-level numbers: accuracy, omission, hallucination (flagged and silent)."""
    fields = _fields(records)
    counts = Counter(f["outcome"] for f in fields)
    given = [f for f in fields if f["expected"] is not None]
    written = [f for f in fields if not _blank(f["value"])]
    unsupported = [f for f in fields if f["outcome"] == "unsupported"]
    correct_formable = [f for f in fields if f["outcome"] == "correct"
                        and f.get("form_kept") is not None]
    return {
        "outcomes": {o: counts.get(o, 0) for o in OUTCOMES},
        "accuracy": rate(sum(f["outcome"] == "correct" for f in given), len(given)),
        "omission_rate": rate(sum(f["outcome"] == "omitted" for f in given), len(given)),
        "hallucination_rate": rate(len(unsupported), len(written)),
        "hallucinations_flagged": rate(sum(f["ai_drafted"] for f in unsupported),
                                       len(unsupported)),
        "grounded_wrong_rate": rate(counts.get("grounded_wrong", 0), len(written)),
        "correctly_empty_rate": rate(counts.get("correctly_empty", 0),
                                     sum(f["expected"] is None for f in fields)),
        "superseded_used": sum(f["superseded"] for f in fields),
        "placeholders": sum(f["placeholder"] for f in fields),
        "form_kept": rate(sum(bool(f["form_kept"]) for f in correct_formable),
                          len(correct_formable)),
    }


def _breakdown(records: list[dict[str, Any]], key) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for field in (record.get("fields") or {}).values():
            groups[key(record, field)].append(field)
    out = {}
    for name, fields in sorted(groups.items()):
        given = [f for f in fields if f["expected"] is not None]
        written = [f for f in fields if not _blank(f["value"])]
        out[name] = {
            "accuracy": rate(sum(f["outcome"] == "correct" for f in given), len(given)),
            "hallucination_rate": rate(sum(f["outcome"] == "unsupported" for f in written),
                                       len(written)),
        }
    return out


def table_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Row counts, cells, and tables written where the notes have none."""
    tables = [t for r in records for t in (r.get("tables") or {}).values()]
    expected = [t for t in tables if t["rows_expected"] is not None]
    return {
        "row_count_ok": rate(sum(bool(t["row_count_ok"]) for t in expected), len(expected)),
        "cell_accuracy": rate(sum(t["cells_correct"] for t in expected),
                              sum(t["cells_expected"] for t in expected)),
        "unsupported_cells": rate(sum(t["cells_unsupported"] for t in tables),
                                  sum(t["cells_written"] for t in tables)),
        "invented_tables": rate(sum(t["invented"] for t in tables),
                                sum(t["rows_expected"] is None for t in tables)),
    }


def free_text_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The rubric grader's verdicts on free-text fields (DESIGN.md §6.5), where it ran."""
    items = [f for r in records for f in (r.get("free") or {}).values()]
    written = [f for f in items if not _blank(f.get("value"))]
    graded = [f for f in written if (f.get("grade") or {}).get("status") == "graded"]
    with_points = [f for f in graded if f.get("points")]
    return {
        "written": rate(len(written), len(items)),
        "graded": rate(len(graded), len(written)),
        "faithful": rate(sum(bool(f["grade"]["faithful"]) for f in graded), len(graded)),
        "complete": rate(sum(bool(f["grade"]["complete"]) for f in with_points),
                         len(with_points)),
        "omitted": rate(sum(1 for f in items if f.get("points") and _blank(f.get("value"))),
                        sum(1 for f in items if f.get("points"))),
        "written_without_source": rate(sum(1 for f in written if not f.get("points")),
                                       sum(1 for f in items if not f.get("points"))),
    }


def pipeline_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Which engine wrote each document, and what the read-back review did."""
    sources = Counter((r.get("routing") or {}).get("source") or "none" for r in records)
    reviewed = [r for r in records if (r.get("review") or {}).get("ran")]
    return {
        "routing_source": dict(sorted(sources.items())),
        "review_ran": rate(len(reviewed), len(records)),
        "review_findings_mean": (sum(r["review"]["findings"] for r in reviewed) / len(reviewed)
                                 if reviewed else None),
        "rewrites": rate(sum(bool(r["review"].get("rewrite")) for r in reviewed), len(reviewed)),
        "layout_preserved": rate(sum(bool((r.get("layout") or {}).get("preserved"))
                                     for r in records), len(records)),
    }


def stability(
    records: list[dict[str, Any]], repeats: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """How often each field's outcome stays the same when a case is generated again."""
    if not repeats:
        return None
    by_id = {r["id"]: r for r in records}
    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for again in repeats:
        if not again.get("error"):
            runs[again["id"]].append(again)
    agree = total = same_value = 0
    for case_id, others in runs.items():
        base = by_id.get(case_id)
        if base is None:
            continue
        for logical, field in (base.get("fields") or {}).items():
            versions = [field] + [(o.get("fields") or {}).get(logical) for o in others]
            if any(v is None for v in versions):
                continue
            total += 1
            agree += len({v["outcome"] for v in versions}) == 1
            same_value += len({norm_text(v["value"] or "") for v in versions}) == 1
    return {
        "cases": len(runs),
        "runs_per_case": 1 + max((len(o) for o in runs.values()), default=0),
        "outcome_agreement": rate(agree, total),
        "value_agreement": rate(same_value, total),
    }


def ai_summary(records: list[dict[str, Any]], repeats: list[dict[str, Any]]) -> dict[str, Any]:
    """Spend, failed calls and stability for a run with AI (errored records already left out)."""
    spends = [r.get("spend_usd") or {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
              for r in records]
    grader = [r.get("grader_spend_usd") or {"live": 0.0, "replayed": 0.0} for r in records]
    calls: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        for call in record.get("ai_calls") or []:
            calls[call["kind"]].append(call["outcome"] != "ok")
    live = sum(s["live"] for s in spends)
    replayed = sum(s["replayed"] for s in spends)
    return {
        "cost_usd": {
            "live": live,
            "replayed": replayed,
            "total": live + replayed,
            "per_document": (live + replayed) / len(records) if records else None,
            "unpriced_calls": sum(int(s.get("unpriced_calls", 0)) for s in spends),
        },
        "grader_cost_usd": {"live": sum(g["live"] for g in grader),
                            "replayed": sum(g["replayed"] for g in grader)},
        "ai_call_failures": {kind: rate(sum(f), len(f)) for kind, f in sorted(calls.items())},
        "fallback_rate": rate(sum((r.get("routing") or {}).get("source") != "writer"
                                  for r in records), len(records)),
        "stability": stability(records, repeats),
    }


def summarize(records: Iterable[dict[str, Any]],
              repeats: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Every generate aggregate for one run."""
    records = list(records)
    ok = _ok(records)
    times = [r["generate_ms"] for r in ok if r.get("generate_ms") is not None]
    ai = any(r.get("ai") for r in records)
    return {
        "cases": len(records),
        "fields": field_metrics(ok),
        "by_kind": _breakdown(ok, lambda record, field: field["kind"]),
        "by_style": _breakdown(ok, lambda record, field: record["style"]),
        "tables": table_metrics(ok),
        "free_text": free_text_metrics(ok),
        "pipeline": pipeline_metrics(ok),
        "generate_ms_p50": percentile(times, 0.50),
        "generate_ms_p95": percentile(times, 0.95),
        "error_rate": rate(len(records) - len(ok), len(records)),
        "ai": ai_summary(ok, list(repeats)) if ai else None,
    }
