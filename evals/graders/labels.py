"""The owner's labels for the rubric grader, and how often the grader agrees with them.

The brief (§6.4) trusts the grader only where it agrees with the owner on at least 85% of 30
hand-labelled items. This module:
- picks the 30 items from the generate results (``sheet``): 10 per mode, across the free-text
  fields (a mode with fewer graded values gives its share to the others), and, where there are
  enough, half from items the grader answered "no" on, so the check isn't all easy "yes" items.
  The choice is a hash, so it is the same every time.
- leaves the grader's verdict and the mode out of what the owner sees, so the labels are blind.
- compares the owner's answers with the grader's, per question (``agreement``). A question whose
  agreement is below 85% is not used: its numbers are reported as "not graded".

``labels/sheet.json`` and ``labels/owner_labels.json`` are committed. The owner's answers come
from the labelling page and are written to the file as given.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evals import jsonfmt
from evals.corpus.notes import load_notes
from evals.metrics.comply import rate
from evals.paths import EVALS_DIR

LABELS_DIR = EVALS_DIR / "graders" / "labels"
SHEET_PATH = LABELS_DIR / "sheet.json"
OWNER_PATH = LABELS_DIR / "owner_labels.json"
AGREEMENT_PATH = LABELS_DIR / "agreement.json"  # written by `python -m evals labels check`
GATE = 0.85
QUESTIONS = ("faithful", "complete")


def _hash(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def graded_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Every graded free-text value in one generate result."""
    config = result["meta"]["config"]
    items = []
    for case in result["cases"]:
        for logical, free in (case.get("free") or {}).items():
            grade = free.get("grade") or {}
            if grade.get("status") == "graded":
                items.append({"config": config, "case": case["id"], "field": logical,
                              "value": free["value"], "points": free.get("points"),
                              "grade": grade})
    return items


def _pick(items: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    def said_no(item):
        return (item["grade"].get("faithful") is False
                or item["grade"].get("complete") is False)

    ranked = sorted(items, key=lambda i: _hash(i["config"], i["case"], i["field"]))
    no = [i for i in ranked if said_no(i)]
    yes = [i for i in ranked if not said_no(i)]
    take_no = min(len(no), n // 2)
    chosen = no[:take_no] + yes[: n - take_no]
    if len(chosen) < n:  # not enough "yes" items: fill with more "no" ones
        chosen += no[take_no: take_no + n - len(chosen)]
    return chosen


def _quotas(pools: dict[str, list[dict[str, Any]]], per_mode: int) -> dict[str, int]:
    """``per_mode`` items from each mode; a mode with fewer gives its share to the others, one
    item at a time, the modes with the most items first."""
    quota = {config: min(per_mode, len(pool)) for config, pool in pools.items()}
    spare = per_mode * len(pools) - sum(quota.values())
    order = sorted(pools, key=lambda c: (-len(pools[c]), c))
    while spare > 0 and any(quota[c] < len(pools[c]) for c in order):
        for config in order:  # one at a time, so the share is spread evenly
            if spare > 0 and quota[config] < len(pools[config]):
                quota[config] += 1
                spare -= 1
    return quota


def sheet(results: list[dict[str, Any]], per_mode: int = 10) -> dict[str, Any]:
    """The items to label, without the grader's verdicts, in a mixed but fixed order."""
    notes = {case.id: case for case in load_notes()}
    pools = {result["meta"]["config"]: graded_items(result) for result in results}
    quota = _quotas(pools, per_mode)
    chosen = [item for config, pool in pools.items() for item in _pick(pool, quota[config])]
    items = []
    for item in sorted(chosen, key=lambda i: _hash("order", i["config"], i["case"], i["field"])):
        case = notes[item["case"]]
        items.append({
            "id": _hash(item["config"], item["case"], item["field"])[:10],
            "source": {"config": item["config"], "case": item["case"], "field": item["field"]},
            "document": case.pair,
            "field": item["field"],
            "notes": case.text,
            "points": item["points"],
            "value": item["value"],
        })
    return {"results": sorted(r["meta"]["config"] for r in results), "items": items}


def write_sheet(data: dict[str, Any], path: Path = SHEET_PATH) -> Path:
    """Write the sheet; it is committed with the results it came from."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jsonfmt.dumps(data) + "\n", encoding="utf-8", newline="\n")
    return path


def agreement(sheet_data: dict[str, Any], owner: dict[str, Any],
              results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per question, how often the grader's verdict equals the owner's, and whether it's used."""
    verdicts = {
        (item["config"], item["case"], item["field"]): item["grade"]
        for result in results for item in graded_items(result)
    }
    labels = owner.get("labels") or {}
    out: dict[str, Any] = {}
    for question in QUESTIONS:
        agree = total = 0
        disagreements = []
        for item in sheet_data["items"]:
            label = (labels.get(item["id"]) or {}).get(question)
            source = item["source"]
            verdict = (verdicts.get((source["config"], source["case"], source["field"]))
                       or {}).get(question)
            if label is None or verdict is None:
                continue  # unlabelled, or "complete" asked of a field the notes leave out
            total += 1
            if bool(label) == bool(verdict):
                agree += 1
            else:
                disagreements.append({"item": item["id"], "owner": bool(label),
                                      "grader": bool(verdict)})
        agreed = rate(agree, total)
        out[question] = {
            "agreement": agreed,
            "used": agreed["value"] is not None and agreed["value"] >= GATE,
            "disagreements": disagreements,
        }
    out["gate"] = GATE
    return out


def load_json(path: Path) -> dict[str, Any]:
    """Read a sheet or labels file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
