"""Analyze metrics (DESIGN.md §5.3): the template DocForge built from k examples, against the
ground truth of the example it took as its representative.

Every ground-truth element gets an **outcome**:
- a fixed element (title, heading, clause, a fixed label): ``kept`` when classified ``FIXED``,
  ``became_field`` when the template asks for it as a field, else ``other``
- a field: ``found`` when classified as a field (dynamic, a repeating section or block), else
  ``missed``
- a table: ``detected`` when classified ``REPEATABLE_TABLE`` with the header row as its columns,
  ``wrong_header`` when repeating with other columns, else ``missed``
- an information block ("label | value" rows): ``form`` when its values are fields and its
  labels stay fixed, ``frozen`` when nothing in it is a field, ``looped`` when it became a
  repeating table, else ``partial``
- the page-number footer: ``auto`` when classified ``AUTO_FIELD``, else ``other``

An information block's cells are scored one by one, as fields and boilerplate. A looped block
keeps its first row as a heading row and repeats the rest, so the labels of those rows become
row data (boilerplate lost) and their values become fillable (fields found); the first row's
value stays frozen.

Field precision, recall and F1 count the top-level elements and the information-block cells.
The cells of an ordinary data table are left out: table detection measures those tables. These
are pure functions: plain data in, numbers out.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from evals.metrics.comply import percentile, rate
from evals.metrics.normalize import norm_text

KS = (1, 2, 3, 5)
_FIELD_CLASSES = ("REPEATABLE_SECTION", "REPEATABLE_BLOCK")
# Which DocForge field types count as right for each ground-truth type. Money has no type of
# its own in DocForge, so a number is right for it (DESIGN.md §10, question 3).
ACCEPTED_TYPES = {
    "text": {"text"},
    "multiline_text": {"multiline_text", "text"},
    "date": {"date"},
    "person": {"person"},
    "number": {"number"},
    "money": {"number"},
    "enum": {"enum"},
}


def category(classification: str | None) -> str:
    """What a DocForge classification makes of an element: fixed, field, table, auto, unknown."""
    if classification == "FIXED":
        return "fixed"
    if classification and (classification.startswith("DYNAMIC_")
                           or classification in _FIELD_CLASSES):
        return "field"
    if classification == "REPEATABLE_TABLE":
        return "table"
    if classification == "AUTO_FIELD":
        return "auto"
    return "unknown"


def type_ok(truth_type: str, predicted: str | None) -> bool | None:
    """Whether DocForge's field type is right for the ground truth's (None: no type to judge)."""
    if predicted is None or truth_type not in ACCEPTED_TYPES:
        return None
    return predicted in ACCEPTED_TYPES[truth_type]


def _columns_ok(columns: list[str] | None, headers: list[str]) -> bool:
    return columns is not None and [norm_text(c) for c in columns] == [
        norm_text(h) for h in headers]


def element_outcome(element: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    """The outcome of one top-level ground-truth element (not an information block).

    ``prediction`` holds the element's DocForge ``class`` (classification), and from its field
    definition the ``field_type`` and, for a table, the ``columns`` (labels).
    """
    cls = prediction.get("class")
    got = category(cls)
    out: dict[str, Any] = {"kind": element["kind"], "class": cls}
    if element["kind"] == "fixed":
        out["outcome"] = ("kept" if got == "fixed"
                          else "became_field" if got in ("field", "table") else "other")
    elif element["kind"] == "field":
        out["field_type"] = element["field_type"]
        out["outcome"] = "found" if got == "field" else "missed"
        out["predicted_type"] = prediction.get("field_type") if got == "field" else None
        out["type_ok"] = type_ok(element["field_type"], out["predicted_type"])
    elif element["kind"] == "table":
        out["columns"] = prediction.get("columns")
        out["outcome"] = ("missed" if got != "table"
                          else "detected" if _columns_ok(out["columns"], element["headers"])
                          else "wrong_header")
    elif element["kind"] == "auto":
        out["outcome"] = "auto" if got == "auto" else "other"
    else:
        raise ValueError(f"no outcome for kind {element['kind']!r}")
    return out


def cell_outcome(cell: dict[str, Any], prediction: dict[str, Any], looped: bool) -> dict[str, Any]:
    """The outcome of one cell of an information block, given whether the block was looped."""
    cls = prediction.get("class")
    own = category(cls) == "field"
    repeated = looped and cell["cell"]["row"] >= 1  # the loop repeats every row but the first
    out: dict[str, Any] = {"kind": cell["kind"], "cell": True, "class": cls,
                           "row": cell["cell"]["row"]}
    if cell["kind"] == "field":
        out["field_type"] = cell["field_type"]
        out["outcome"] = "found" if own or repeated else "missed"
    else:
        out["outcome"] = "became_field" if own or repeated else "kept"
    return out


def info_outcome(block: dict[str, Any], prediction: dict[str, Any],
                 cells: list[dict[str, Any]]) -> dict[str, Any]:
    """The outcome of an information block as a whole, from its cells' outcomes."""
    cls = prediction.get("class")
    values = [c for c in cells if c["kind"] == "field"]
    fixed = [c for c in cells if c["kind"] == "fixed"]
    if category(cls) == "table":
        outcome = "looped"
    elif all(c["outcome"] == "found" for c in values) and all(
            c["outcome"] == "kept" for c in fixed):
        outcome = "form"
    elif not any(c["outcome"] in ("found", "became_field") for c in cells):
        outcome = "frozen"
    else:
        outcome = "partial"
    return {"kind": "info_table", "class": cls, "outcome": outcome}


def case_outcomes(truth: list[dict[str, Any]],
                  predictions: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every element's outcome, cells included, keyed by logical ID.

    ``predictions`` maps every logical ID (cells too) to what DocForge made of its node.
    """
    out: dict[str, dict[str, Any]] = {}
    for element in truth:
        prediction = predictions.get(element["id"], {})
        if element["kind"] != "info_table":
            out[element["id"]] = element_outcome(element, prediction)
            continue
        looped = category(prediction.get("class")) == "table"
        cells = []
        for cell in element["cells"]:
            out[cell["id"]] = cell_outcome(cell, predictions.get(cell["id"], {}), looped)
            cells.append(out[cell["id"]])
        out[element["id"]] = info_outcome(element, prediction, cells)
    return out


def template_layout(truth: list[dict[str, Any]], source: list[tuple], template: list[tuple],
                    outcomes: dict[str, dict[str, Any]]) -> list[str]:
    """What the published template lost of the representative's layout; empty when nothing.

    ``source`` and ``template`` are skeletons (``evals.corpus.ground_truth.skeleton``), and the
    approach follows DocForge's own ``test_template_keeps_its_layout.py``. Every block comes back
    in order with its style; a block the analysis kept fixed keeps its exact text; a labelled
    field keeps its label; a data table keeps its column count and its header row; and an
    information block keeps its column count and every row's label, in order (a loop keeps only
    the first). An information block's values may turn into tags, its first row's too: that is
    what a form looks like. Extra paragraphs and rows (the template's ``{%p … %}`` and
    ``{%tr … %}`` markers) are allowed.
    """
    body = [item for item in template if item[0] == "body"]
    original = [item for item in source if item[0] == "body"]
    problems: list[str] = []
    position = 0
    for element in sorted((e for e in truth if e["locator"]["scope"] == "body"),
                          key=lambda e: e["locator"]["block"]):
        block = original[element["locator"]["block"]]
        kept = (outcomes.get(element["id"]) or {}).get("outcome") == "kept"
        if block[1] == "table":
            width = len(block[2][0])
            # A data table's header row stays as it is; an information block's first row is a
            # label and a value, and only the label is fixed.
            first = (block[2][0][:1] if element["kind"] == "info_table"
                     else tuple(block[2][0]))

            def wanted(item, first=first, width=width):
                return (item[1] == "table" and bool(item[2]) and len(item[2][0]) == width
                        and tuple(item[2][0][:len(first)]) == tuple(first))
        elif kept:
            def wanted(item, block=block):
                return item[1:] == block[1:]
        elif element["kind"] == "field" and element.get("label"):
            prefix = norm_text(element["label"])

            def wanted(item, block=block, prefix=prefix):
                return (item[1] == "paragraph" and item[3] == block[3]
                        and norm_text(item[2]).startswith(prefix))
        else:
            def wanted(item, block=block):
                return item[1] == "paragraph" and item[3] == block[3]
        found = next((i for i in range(position, len(body)) if wanted(body[i])), None)
        if found is None:
            problems.append(f"{element['id']}: missing or out of order")
            continue
        position = found + 1
        if element["kind"] == "info_table":
            labels = [row[0] for row in element["rows"]]
            kept = [row[0] for row in body[found][2]]
            if not _in_order(labels, kept):
                problems.append(f"{element['id']}: rows or labels lost")
    return problems


def _in_order(wanted: list[str], seen: list[str]) -> bool:
    """Whether every item of ``wanted`` appears in ``seen``, in the same order."""
    rest = iter(seen)
    return all(any(item == other for other in rest) for item in wanted)


# --- aggregates --------------------------------------------------------------------------


def f1(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """F1 with its counts; None when there is nothing to score."""
    den = 2 * tp + fp + fn
    return {"value": 2 * tp / den if den else None, "tp": tp, "fp": fp, "fn": fn}


def _ok(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if not r.get("error")]


def _types(found: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [o for o in found if o.get("type_ok") is not None]
    return rate(sum(bool(o["type_ok"]) for o in judged), len(judged))


def quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The quality metrics over a set of cases (pooled over their elements)."""
    outcomes = [(r, o) for r in records for o in (r.get("outcomes") or {}).values()]
    scored = [o for _r, o in outcomes if o["kind"] in ("field", "fixed")]
    tp = sum(o["kind"] == "field" and o["outcome"] == "found" for o in scored)
    fn = sum(o["kind"] == "field" and o["outcome"] == "missed" for o in scored)
    fp = sum(o["kind"] == "fixed" and o["outcome"] == "became_field" for o in scored)
    fixed = [o for o in scored if o["kind"] == "fixed"]
    found = [(r, o) for r, o in outcomes
             if o["kind"] == "field" and not o.get("cell") and o["outcome"] == "found"]
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_lang: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record, outcome in found:
        by_kind[outcome["field_type"]].append(outcome)
        by_lang[record["lang"]].append(outcome)
    tables = [o for _r, o in outcomes if o["kind"] == "table"]
    info = [o for _r, o in outcomes if o["kind"] == "info_table"]
    values = [o for o in scored if o.get("cell") and o["kind"] == "field"]
    autos = [o for _r, o in outcomes if o["kind"] == "auto"]
    return {
        "cases": len(records),
        "field_precision": rate(tp, tp + fp),
        "field_recall": rate(tp, tp + fn),
        "field_f1": f1(tp, fp, fn),
        "boilerplate_kept": rate(sum(o["outcome"] == "kept" for o in fixed), len(fixed)),
        "type_accuracy": _types([o for _r, o in found]),
        "types_by_kind": {kind: _types(items) for kind, items in sorted(by_kind.items())},
        "types_by_lang": {lang: _types(items) for lang, items in sorted(by_lang.items())},
        "tables_detected": rate(sum(o["outcome"] == "detected" for o in tables), len(tables)),
        "info_tables": dict(sorted(Counter(o["outcome"] for o in info).items())),
        "info_values_found": rate(sum(o["outcome"] == "found" for o in values), len(values)),
        "auto_fields": rate(sum(o["outcome"] == "auto" for o in autos), len(autos)),
        "layout_preserved": rate(sum(bool((r.get("layout") or {}).get("preserved"))
                                     for r in records), len(records)),
    }


def shared_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The shared-value cases: is the value both examples share still a field?"""
    outcomes = [(r["outcomes"] or {}).get(r["shared_field"]) for r in records]
    judged = [o for o in outcomes if o is not None]
    return {
        "shared_field_found": rate(sum(o["outcome"] == "found" for o in judged), len(judged)),
        "missed": sorted(r["pair"] for r, o in zip(records, outcomes, strict=True)
                         if o is not None and o["outcome"] != "found"),
        "quality": quality(records),
    }


def by_pair(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Field F1 and boilerplate kept per type and k, for the write-up."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for record in sorted(records, key=lambda r: (r["pair"], r["k"])):
        metrics = quality([record])
        out[record["pair"]][str(record["k"])] = {
            "field_f1": metrics["field_f1"]["value"],
            "boilerplate_kept": metrics["boilerplate_kept"]["value"],
        }
    return dict(out)


def stability(records: list[dict[str, Any]],
              repeats: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How often each element's outcome stays the same when a case is analyzed again."""
    if not repeats:
        return None
    by_id = {r["id"]: r for r in records}
    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for again in repeats:
        if not again.get("error"):
            runs[again["id"]].append(again)
    agree = total = 0
    for case_id, others in runs.items():
        base = by_id.get(case_id)
        if base is None:
            continue
        for logical, outcome in (base.get("outcomes") or {}).items():
            versions = [outcome] + [(o.get("outcomes") or {}).get(logical) for o in others]
            if any(v is None for v in versions):
                continue
            total += 1
            agree += len({v["outcome"] for v in versions}) == 1
    return {
        "cases": len(runs),
        "runs_per_case": 1 + max((len(o) for o in runs.values()), default=0),
        "outcome_agreement": rate(agree, total),
    }


def ai_summary(records: list[dict[str, Any]], repeats: list[dict[str, Any]]) -> dict[str, Any]:
    """Spend, failed calls, fallbacks and stability for a run with AI."""
    spends = [r.get("spend_usd") or {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
              for r in records]
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
            "per_analysis": (live + replayed) / len(records) if records else None,
            "unpriced_calls": sum(int(s.get("unpriced_calls", 0)) for s in spends),
        },
        "ai_call_failures": {kind: rate(sum(f), len(f)) for kind, f in sorted(calls.items())},
        "fallback_rate": rate(sum(r.get("source") == "heuristic_fallback" for r in records),
                              len(records)),
        "stability": stability(records, repeats),
    }


def summarize(records: Iterable[dict[str, Any]],
              repeats: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    """Every analyze aggregate for one run: quality by number of examples, then the rest."""
    records = list(records)
    ok = _ok(records)
    examples = [r for r in ok if r["group"] == "examples"]
    shared = [r for r in ok if r["group"] == "shared"]
    times = [r["analyze_ms"] for r in ok if r.get("analyze_ms") is not None]
    ai = any(r.get("ai") for r in records)
    return {
        "cases": len(records),
        "by_k": {str(k): quality([r for r in examples if r["k"] == k]) for k in KS},
        "all_examples": quality(examples),
        "shared": shared_metrics(shared) if shared else None,
        "by_pair": by_pair(examples),
        "sources": dict(sorted(Counter(r.get("source") or "none" for r in ok).items())),
        "analyze_ms_p50": percentile(times, 0.50),
        "analyze_ms_p95": percentile(times, 0.95),
        "error_rate": rate(len(records) - len(ok), len(records)),
        "ai": ai_summary(ok, list(repeats)) if ai else None,
    }
