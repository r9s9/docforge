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


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Every comply aggregate for one run."""
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
    fixable = [r for r, _a in material if r["label"].get("fixable")]
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
