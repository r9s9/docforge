"""Comply metrics (DESIGN.md §5.1), computed from the runner's case records.

A case record is a plain dict: the case's ``label`` from the manifest, what DocForge reported
(``differences`` with their logical IDs, ``extras`` from the alignment, ``score``, ``grade``),
timings, an optional ``fix`` result and an optional ``error``.

Definitions:
- A difference **belongs** to the injected deviation when it sits on one of the label's
  targets; otherwise it is **spurious**.
- A deviation is **found** when a difference belongs to it. An inserted paragraph has no place
  in the template, so it is found only through an ``extra`` alignment row holding its text.
- An **alarm** is any difference with severity error or warning, anywhere in the document.
- Every rate carries its numerator and denominator. Cases that errored are counted, then left
  out of every denominator except the error rate's.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

ALARM_SEVERITIES = ("error", "warning")
FIXED_KINDS = ("changed_fixed", "missing_fixed")


def rate(num: int, den: int) -> dict[str, Any]:
    """A rate with its counts; ``value`` is None when nothing was counted."""
    return {"value": (num / den) if den else None, "num": num, "den": den}


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def attribute(record: dict[str, Any]) -> dict[str, Any]:
    """What happened to one case's deviation: found, right kind, alarms, spurious differences."""
    label = record["label"]
    targets = set(label["targets"])
    differences = record.get("differences") or []
    on_target = [d for d in differences if d.get("logical_id") in targets]
    spurious = [d for d in differences if d.get("logical_id") not in targets]
    if label["mutator"].startswith("insert_"):
        inserted = _norm(label["detail"].get("text", ""))
        found = any(inserted and inserted in _norm(extra) for extra in record.get("extras") or [])
        kind_ok = None
    else:
        found = bool(on_target)
        expected = label.get("expected_kind")
        kind_ok = any(d["kind"] == expected for d in on_target) if (found and expected) else None
    alarms = [d for d in differences if d.get("severity") in ALARM_SEVERITIES]
    return {
        "found": found,
        "kind_ok": kind_ok,
        "alarm": bool(alarms),
        "alarms": len(alarms),
        "spurious": len(spurious),
    }


def auc(higher: Sequence[float], lower: Sequence[float]) -> float | None:
    """Chance that a value from ``higher`` beats one from ``lower``; ties count half."""
    if not higher or not lower:
        return None
    wins = sum(1.0 if h > low else 0.5 if h == low else 0.0 for h in higher for low in lower)
    return wins / (len(higher) * len(lower))


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (``q`` in 0..1); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _group(record: dict[str, Any]) -> str:
    """clean | material | benign"""
    label = record["label"]
    if label["mutator"] == "none":
        return "clean"
    return "material" if label["material"] else "benign"


def fix_outcome(fix: dict[str, Any]) -> bool:
    """A fix succeeds when the re-check is clean, values are kept and the text is restored."""
    return bool(fix["recheck_clean"] and fix["values_kept"] and fix["text_restored"])


def summarize(
    records: Iterable[dict[str, Any]], repeats: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    """Every comply aggregate for one run (``repeats`` feed the stability numbers)."""
    records = list(records)
    ok = [r for r in records if not r.get("error")]
    seen = [(r, attribute(r)) for r in ok]
    material = [(r, a) for r, a in seen if _group(r) == "material"]
    benign = [(r, a) for r, a in seen if _group(r) == "benign"]
    clean = [(r, a) for r, a in seen if _group(r) == "clean"]
    found = [(r, a) for r, a in material if a["found"]]
    typed = [(r, a) for r, a in found if a["kind_ok"] is not None]
    mutated = material + benign

    by_kind: dict[str, list[bool]] = defaultdict(list)
    for r, a in material:
        by_kind[r["label"].get("expected_kind") or "extra"].append(a["found"])

    grades: dict[str, dict[str, int]] = {}
    for r, _a in seen:
        row = grades.setdefault(_group(r), {"pass": 0, "warning": 0, "fail": 0})
        row[r["grade"]] = row.get(r["grade"], 0) + 1

    fixes = [r["fix"] for r, _a in material if r["label"].get("fixable") and r.get("fix")]
    # Fixes run in the no-AI run only; elsewhere their numbers are "n/a", not zero.
    fixable = [r for r, _a in material if r["label"].get("fixable")] if fixes else []
    latencies = [r["check_ms"] for r in ok if r.get("check_ms") is not None]

    return {
        "cases": len(records),
        "detection_recall": rate(sum(a["found"] for _r, a in material), len(material)),
        "detection_by_kind": {
            kind: rate(sum(hits), len(hits)) for kind, hits in sorted(by_kind.items())
        },
        "kind_accuracy": rate(sum(bool(a["kind_ok"]) for _r, a in typed), len(typed)),
        "benign_alarm_rate": rate(sum(a["alarm"] for _r, a in benign), len(benign)),
        "false_alarm_rate_clean": rate(sum(a["alarm"] for _r, a in clean), len(clean)),
        "mean_alarms_clean": (
            sum(a["alarms"] for _r, a in clean) / len(clean) if clean else None
        ),
        "spurious_per_mutated_case": (
            sum(a["spurious"] for _r, a in mutated) / len(mutated) if mutated else None
        ),
        "score_auc_clean_vs_material": auc(
            [r["score"] for r, _a in clean], [r["score"] for r, _a in material]
        ),
        "grades": grades,
        "fix_success": rate(sum(fix_outcome(f) for f in fixes), len(fixable)),
        "fix_recheck_clean": rate(sum(bool(f["recheck_clean"]) for f in fixes), len(fixable)),
        "fix_values_kept": rate(sum(bool(f["values_kept"]) for f in fixes), len(fixable)),
        "fix_text_restored": rate(sum(bool(f["text_restored"]) for f in fixes), len(fixable)),
        "fix_style_restored": rate(sum(bool(f["style_restored"]) for f in fixes), len(fixable)),
        "check_ms_p50": percentile(latencies, 0.50),
        "check_ms_p95": percentile(latencies, 0.95),
        "error_rate": rate(len(records) - len(ok), len(records)),
        "by_mutator": by_mutator(seen),
        "ai": ai_summary(ok, list(repeats)) if is_ai_run(records) else None,
    }


def by_mutator(seen: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    """One row per mutator and materiality (and the clean controls): the console table's counts.

    Materiality can differ within one mutator (deleting the minutes' distribution note is
    benign, deleting a confidentiality clause is not), so the two get separate rows.
    """
    rows: dict[tuple[str, bool], dict[str, Any]] = {}
    for record, outcome in seen:
        label = record["label"]
        row = rows.setdefault(
            (label["mutator"], label["material"]),
            {
                "mutator": label["mutator"],
                "expected_kind": label.get("expected_kind"),
                "material": label["material"],
                "n": 0,
                "found": 0,
                "kind_ok": 0,
                "alarms": 0,
                "score_sum": 0.0,
            },
        )
        row["n"] += 1
        row["found"] += int(outcome["found"])
        row["kind_ok"] += int(bool(outcome["kind_ok"]))
        row["alarms"] += int(outcome["alarm"])
        row["score_sum"] += record["score"]
    for row in rows.values():
        row["mean_score"] = round(row.pop("score_sum") / row["n"], 1)
    return list(rows.values())


# --- AI modes --------------------------------------------------------------------------------


def _judge_status(record: dict[str, Any]) -> str | None:
    return (record.get("judge") or {}).get("status")


def is_ai_run(records: Iterable[dict[str, Any]]) -> bool:
    """Whether the run had DocForge's AI on (the judge was at least asked about)."""
    return any(_judge_status(r) in ("ran", "failed", "not_needed") for r in records)


def judge_matrix(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The judge's material/benign calls against ground truth, over every judged difference.

    A difference on the injected deviation's target takes that deviation's label; any other
    difference (spurious, or on a clean control) is benign. Differences without a verdict
    (past the judge's 40-item cap, or missing from its answer) are counted as not judged.
    """
    tp = fp = fn = tn = not_judged = 0
    for record in records:
        if _judge_status(record) != "ran":
            continue
        label = record["label"]
        targets = set(label["targets"])
        for difference in record["differences"]:
            verdict = difference.get("verdict")
            if verdict is None:
                not_judged += 1
                continue
            truth = bool(label["material"]) and difference.get("logical_id") in targets
            predicted = bool(verdict["material"])
            if predicted and truth:
                tp += 1
            elif predicted:
                fp += 1
            elif truth:
                fn += 1
            else:
                tn += 1
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": rate(tp, tp + fp),
        "recall": rate(tp, tp + fn),
        "accuracy": rate(tp + tn, tp + fp + fn + tn),
        "not_judged": not_judged,
    }


def semantic_score(record: dict[str, Any]) -> float | None:
    """The judge's semantic score; 100 when there was nothing to judge; None if it failed."""
    status = _judge_status(record)
    if status == "ran":
        return record["dimensions"].get("semantic")
    if status == "not_needed":
        return 100.0
    return None


def material_alarms_kept(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Found material deviations still flagged error/warning on their target after the judge."""
    kept = found = 0
    for record in records:
        label = record["label"]
        if label["mutator"] == "none" or not label["material"] or not label["targets"]:
            continue
        on_target = [d for d in record["differences"]
                     if d.get("logical_id") in set(label["targets"])]
        if not on_target:
            continue
        found += 1
        kept += any(d.get("severity") in ALARM_SEVERITIES for d in on_target)
    return rate(kept, found)


def cost_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Spend in USD (DocForge's price table): totals, per document and per judged document."""
    spends = [r.get("spend_usd") or {"live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
              for r in records]
    live = sum(s["live"] for s in spends)
    replayed = sum(s["replayed"] for s in spends)
    judged = [s["live"] + s["replayed"]
              for r, s in zip(records, spends, strict=True) if _judge_status(r) == "ran"]
    return {
        "live": live,
        "replayed": replayed,
        "total": live + replayed,
        "per_document": (live + replayed) / len(records) if records else None,
        "per_judged_document": sum(judged) / len(judged) if judged else None,
        "unpriced_calls": sum(int(s.get("unpriced_calls", 0)) for s in spends),
    }


def ai_call_failures(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Per call kind: calls that raised (DocForge then falls back) over all calls."""
    calls: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        for call in record.get("ai_calls") or []:
            calls[call["kind"]].append(call["outcome"] != "ok")
    return {kind: rate(sum(failed), len(failed)) for kind, failed in sorted(calls.items())}


def stability(
    records: list[dict[str, Any]], repeats: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """How often the judge's verdicts and semantic score stay the same across repeats."""
    if not repeats:
        return None
    by_id = {r["id"]: r for r in records}
    runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for again in repeats:
        if not again.get("error"):
            runs[again["id"]].append(again)
    agree = total = 0
    spreads: list[float] = []
    for case_id, others in runs.items():
        base = by_id.get(case_id)
        if base is None:
            continue
        verdict_runs = [[d.get("verdict") for d in base["differences"]]]
        verdict_runs += [again["verdicts"] for again in others]
        for index in range(len(verdict_runs[0])):
            calls = [run[index] if index < len(run) else None for run in verdict_runs]
            if any(call is None for call in calls):
                continue
            total += 1
            agree += len({bool(call["material"]) for call in calls}) == 1
        scores = [s for s in [semantic_score(base)] + [a["semantic"] for a in others]
                  if s is not None]
        if len(scores) > 1:
            spreads.append(max(scores) - min(scores))
    return {
        "cases": len(runs),
        "runs_per_case": 1 + max((len(o) for o in runs.values()), default=0),
        "verdict_agreement": rate(agree, total),
        "semantic_spread_mean": sum(spreads) / len(spreads) if spreads else None,
    }


def ai_summary(records: list[dict[str, Any]], repeats: list[dict[str, Any]]) -> dict[str, Any]:
    """The AI-mode aggregates of a run (records that errored are already left out)."""
    clean = [r for r in records if _group(r) == "clean"]
    material = [r for r in records if _group(r) == "material"]
    statuses = [_judge_status(r) for r in records]
    return {
        "judge": judge_matrix(records),
        "judge_fallback_rate": rate(statuses.count("failed"),
                                    statuses.count("ran") + statuses.count("failed")),
        "semantic_auc_clean_vs_material": auc(
            [s for r in clean if (s := semantic_score(r)) is not None],
            [s for r in material if (s := semantic_score(r)) is not None],
        ),
        "material_alarms_kept": material_alarms_kept(records),
        "cost_usd": cost_summary(records),
        "ai_call_failures": ai_call_failures(records),
        "stability": stability(records, repeats),
    }
