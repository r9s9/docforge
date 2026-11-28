"""The CI gate (DESIGN.md §8): no-AI results checked against ``evals/thresholds.yaml``.

The no-AI path is deterministic, so the thresholds sit at the committed baseline. Any drop in a
key metric fails, and so does losing a single material deviation the comply suite found before:
that is "a PR that breaks a mutator-detected case fails CI". The results must also have run on
the corpus, notes and analyze documents the thresholds were set on (their hashes), since other
cases make the numbers incomparable; only a deliberate ``gate --update`` accepts that. An
improvement passes, with a note to raise the thresholds in the same PR.

Pure functions over result documents; the CLI reads and writes the files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from evals.metrics.comply import attribute

SUITES = ("comply", "generate", "analyze")
KS = ("1", "2", "3", "5")
_EPSILON = 1e-9


@dataclass(frozen=True)
class Metric:
    """One gated metric: where it sits in a suite's aggregates, and which way is worse."""

    key: str
    label: str
    path: tuple[str, ...]
    direction: str  # "min": must not fall; "max": must not rise


def _analyze_metrics() -> list[Metric]:
    metrics = []
    for k in KS:
        examples = "1 example" if k == "1" else f"{k} examples"
        metrics += [
            Metric(f"field_f1_k{k}", f"field F1, {examples}", ("by_k", k, "field_f1"), "min"),
            Metric(f"boilerplate_kept_k{k}", f"boilerplate kept, {examples}",
                   ("by_k", k, "boilerplate_kept"), "min"),
            Metric(f"types_right_k{k}", f"field types right, {examples}",
                   ("by_k", k, "type_accuracy"), "min"),
            Metric(f"tables_detected_k{k}", f"tables detected, {examples}",
                   ("by_k", k, "tables_detected"), "min"),
            Metric(f"layout_kept_k{k}", f"layout kept, {examples}",
                   ("by_k", k, "layout_preserved"), "min"),
        ]
    return metrics + [
        Metric("shared_value_found", "shared value still a field",
               ("shared", "shared_field_found"), "min"),
        Metric("errors", "errors", ("error_rate",), "max"),
    ]


METRICS: dict[str, list[Metric]] = {
    "comply": [
        Metric("detection_recall", "material deviations found", ("detection_recall",), "min"),
        Metric("kind_accuracy", "kind accuracy (when found)", ("kind_accuracy",), "min"),
        Metric("fix_success", "fix success", ("fix_success",), "min"),
        Metric("benign_alarm_rate", "benign changes that alarm", ("benign_alarm_rate",), "max"),
        Metric("false_alarm_rate_clean", "clean controls that alarm",
               ("false_alarm_rate_clean",), "max"),
        Metric("score_auc", "score AUC clean > material", ("score_auc_clean_vs_material",),
               "min"),
        Metric("errors", "errors", ("error_rate",), "max"),
    ],
    "generate": [
        Metric("fields_right", "short fields right", ("fields", "accuracy"), "min"),
        Metric("hallucinated", "hallucinated", ("fields", "hallucination_rate"), "max"),
        Metric("grounded_wrong", "from the notes, but wrong", ("fields", "grounded_wrong_rate"),
               "max"),
        Metric("correctly_empty", "empty where the notes are silent",
               ("fields", "correctly_empty_rate"), "min"),
        Metric("cells_right", "table cells right", ("tables", "cell_accuracy"), "min"),
        Metric("layout_kept", "layout kept", ("pipeline", "layout_preserved"), "min"),
        Metric("errors", "errors", ("error_rate",), "max"),
    ],
    "analyze": _analyze_metrics(),
}


def _get(aggregates: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = aggregates
    for key in path:
        value = (value or {}).get(key) if isinstance(value, dict) else None
    return value


def measure(result: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    """The gated metrics of one result, keyed as in the thresholds file.

    A rate keeps its counts (``value``, ``num``, ``den``), an F1 its ``tp``, ``fp`` and ``fn``,
    and an AUC is a bare ``value``. None when the result doesn't have the metric.
    """
    suite = result["meta"]["suite"]
    out: dict[str, dict[str, Any] | None] = {}
    for metric in METRICS[suite]:
        raw = _get(result["aggregates"], metric.path)
        if raw is None:
            out[metric.key] = None
        elif isinstance(raw, dict):
            out[metric.key] = {k: v for k, v in raw.items() if k in ("value", "num", "den", "tp",
                                                                       "fp", "fn")}
        else:
            out[metric.key] = {"value": raw}
    return out


def detected(result: dict[str, Any]) -> list[str]:
    """The material deviations a comply result found, by case ID."""
    return sorted(record["id"] for record in result["cases"]
                  if not record.get("error") and record["label"]["mutator"] != "none"
                  and record["label"]["material"] and attribute(record)["found"])


def thresholds_from(results: dict[str, dict[str, Any]],
                    names: dict[str, str]) -> dict[str, Any]:
    """The thresholds file's content, set at these no-AI results (one per suite)."""
    out: dict[str, Any] = {}
    for suite in SUITES:
        result = results[suite]
        meta = result["meta"]
        entry: dict[str, Any] = {
            "from": names[suite],
            "corpus_hash": meta["corpus_hash"],
            "metrics": measure(result),
        }
        for key in ("notes_hash", "analyze_hash"):
            if meta.get(key):
                entry[key] = meta[key]
        if suite == "comply":
            entry["detected"] = detected(result)
        out[suite] = entry
    return out


def _counts(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("value") is None:
        return "n/a"
    if "den" in entry:
        return f"{entry['value']:.2f} ({entry['num']}/{entry['den']})"
    if "tp" in entry:
        return f"{entry['value']:.2f} (tp {entry['tp']} · fp {entry['fp']} · fn {entry['fn']})"
    return f"{entry['value']:.2f}"


def _compare(metric: Metric, want: dict[str, Any] | None,
             now: dict[str, Any] | None) -> tuple[str, str]:
    """(status, note): status is ``ok``, ``better`` or ``FAIL``."""
    if want is None or want.get("value") is None:
        return ("ok", "") if now is None or now.get("value") is None else ("better", "new")
    if now is None or now.get("value") is None:
        return "FAIL", "missing"
    sign = 1 if metric.direction == "min" else -1
    delta = sign * (now["value"] - want["value"])
    if delta < -_EPSILON:
        return "FAIL", "worse"
    return ("better", "improved") if delta > _EPSILON else ("ok", "")


def check(thresholds: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Every check of the gate: metric rows, lost and new detections, and problems."""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    lost: list[str] = []
    gained: list[str] = []
    for suite in SUITES:
        want = thresholds.get(suite)
        if want is None:
            continue
        result = results.get(suite)
        if result is None:
            problems.append(f"{suite}: no result given")
            continue
        meta = result["meta"]
        if (meta.get("ai") or {}).get("enabled"):
            problems.append(f"{suite}: the gate takes no-AI results, not {meta['config']}")
            continue
        for key in ("corpus_hash", "notes_hash", "analyze_hash"):
            if want.get(key) and meta.get(key) != want[key]:
                problems.append(f"{suite}: {key} {str(meta.get(key))[:12]} differs from the "
                                f"thresholds' {want[key][:12]}: other cases")
        now = measure(result)
        for metric in METRICS[suite]:
            threshold = (want.get("metrics") or {}).get(metric.key)
            status, note = _compare(metric, threshold, now.get(metric.key))
            rows.append({"suite": suite, "check": metric.label,
                         "threshold": ("≥ " if metric.direction == "min" else "≤ ")
                         + _counts(threshold),
                         "now": _counts(now.get(metric.key)), "status": status, "note": note})
        if suite == "comply" and "detected" in want:
            found = set(detected(result))
            lost += [case for case in want["detected"] if case not in found]
            gained += sorted(found - set(want["detected"]))
            kept = len(want["detected"]) - len(lost)
            rows.append({"suite": suite, "check": "deviations found before, still found",
                         "threshold": f"{len(want['detected'])}/{len(want['detected'])}",
                         "now": f"{kept}/{len(want['detected'])}",
                         "status": "FAIL" if lost else ("better" if gained else "ok"),
                         "note": f"{len(lost)} lost" if lost else
                         (f"{len(gained)} new" if gained else "")})
    failed = problems or lost or any(row["status"] == "FAIL" for row in rows)
    return {"passed": not failed, "rows": rows, "problems": problems, "lost": lost,
            "gained": gained, "improved": any(row["status"] == "better" for row in rows)}


def render(report: dict[str, Any], thresholds_name: str) -> str:
    """The gate's console report."""
    lines = [f"DocForge evals gate · thresholds from {thresholds_name}", ""]
    rows = report["rows"]
    if rows:
        widths = [max(len(str(row[key])) for row in rows + [{"suite": "suite",
                  "check": "check", "threshold": "threshold", "now": "now"}])
                  for key in ("suite", "check", "threshold", "now")]
        header = ("suite", "check", "threshold", "now")
        lines.append("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True))
                     + "  status")
        for row in rows:
            cells = [str(row[key]).ljust(w) for key, w in zip(header, widths, strict=True)]
            status = row["status"] + (f" ({row['note']})" if row["note"] else "")
            lines.append("  ".join(cells) + "  " + status)
    for problem in report["problems"]:
        lines.append(f"PROBLEM: {problem}")
    if report["lost"]:
        lines += ["", f"Lost detections ({len(report['lost'])}): material deviations the "
                  "baseline found and this run doesn't:"]
        lines += [f"  {case}" for case in report["lost"]]
    if report["gained"]:
        lines += ["", f"New detections ({len(report['gained'])}):"]
        lines += [f"  {case}" for case in report["gained"]]
    lines.append("")
    if report["passed"]:
        lines.append("PASSED: no key metric fell, and every deviation found before is still "
                     "found.")
        if report["improved"]:
            lines.append("Some results improved: raise the thresholds in this PR with "
                         "`python -m evals gate --update` on these results.")
    else:
        lines.append("FAILED: the results fell below evals/thresholds.yaml (see above).")
    return "\n".join(lines)


HEADER = """\
# The CI gate's thresholds (DESIGN.md §8), set at the committed no-AI results named below.
# Written by `python -m evals gate --update`; don't edit by hand. A run fails when it ran on
# other cases (the hashes), when a value falls below its `min` threshold (or rises above a `max`
# one), or when a deviation listed under `detected` is no longer found.
"""


def to_yaml(content: dict[str, Any]) -> str:
    """The thresholds file: one line per metric, the detected cases one per line.

    Values are written as JSON, which YAML reads as it is, so hashes and IDs stay strings.
    """
    directions = {suite: {m.key: m.direction for m in METRICS[suite]} for suite in SUITES}
    lines = [HEADER.rstrip("\n")]
    for suite, entry in content.items():
        lines += ["", f"{suite}:"]
        for key in ("from", "corpus_hash", "notes_hash", "analyze_hash"):
            if key in entry:
                lines.append(f"  {key}: {json.dumps(entry[key])}")
        lines.append("  metrics:")
        for key, value in entry["metrics"].items():
            lines.append(f"    {key}: {json.dumps(value)}  # {directions[suite][key]}")
        if "detected" in entry:
            lines.append(f"  detected:  # {len(entry['detected'])} material deviations")
            lines += [f"    - {json.dumps(case)}" for case in entry["detected"]]
    return "\n".join(lines) + "\n"
