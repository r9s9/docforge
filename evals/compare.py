"""Compare comply results side by side, and list the cases whose outcome changed.

``python -m evals compare A.json B.json [C.json ...]`` prints one column per result file (the
M2 "done" table) and, for every file after the first, the cases whose alarm status differs from
the first file. That's mostly what the AI judge changes: it can downgrade a difference to info,
or raise one to error. ``--markdown`` prints the table as Markdown for the docs.

Only result files are read. Every number comes from a run, and the one metric recomputed here
from the case records (``material still alarming``) uses the metric code in
``evals/metrics/comply.py``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evals.metrics.comply import ALARM_SEVERITIES, material_alarms_kept


def load(path: Path) -> dict[str, Any]:
    """Read a result file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rate(r: dict[str, Any] | None) -> str:
    if not r or r.get("value") is None:
        return "n/a"
    return f"{r['value']:.2f} ({r['num']}/{r['den']})"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.4f}" if value < 0.1 else f"${value:.2f}"


def _ai(result: dict[str, Any]) -> dict[str, Any] | None:
    return result["aggregates"].get("ai")


def _cost(result: dict[str, Any], key: str) -> str:
    ai = _ai(result)
    if ai is None:
        return "$0 (no AI)"
    cost = ai["cost_usd"]
    if cost["unpriced_calls"] and not cost["total"]:
        return "$0 (hardware)"
    return _usd(cost[key])


def _ok(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [case for case in result["cases"] if not case.get("error")]


ROWS: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
    ("material deviations found", lambda r: _rate(r["aggregates"]["detection_recall"])),
    ("kind accuracy (when found)", lambda r: _rate(r["aggregates"]["kind_accuracy"])),
    ("material still alarming", lambda r: _rate(material_alarms_kept(_ok(r)))),
    ("benign changes that alarm", lambda r: _rate(r["aggregates"]["benign_alarm_rate"])),
    ("clean controls that alarm", lambda r: _rate(r["aggregates"]["false_alarm_rate_clean"])),
    ("judge: material precision",
     lambda r: _rate(_ai(r)["judge"]["precision"]) if _ai(r) else "n/a"),
    ("judge: material recall", lambda r: _rate(_ai(r)["judge"]["recall"]) if _ai(r) else "n/a"),
    ("judge: accuracy", lambda r: _rate(_ai(r)["judge"]["accuracy"]) if _ai(r) else "n/a"),
    ("judge fell back", lambda r: _rate(_ai(r)["judge_fallback_rate"]) if _ai(r) else "n/a"),
    ("judge stable across repeats",
     lambda r: _rate((_ai(r)["stability"] or {}).get("verdict_agreement")) if _ai(r) else "n/a"),
    ("score AUC clean > material",
     lambda r: _num(r["aggregates"]["score_auc_clean_vs_material"])),
    ("semantic AUC clean > material",
     lambda r: _num(_ai(r)["semantic_auc_clean_vs_material"]) if _ai(r) else "n/a"),
    ("cost per document", lambda r: _cost(r, "per_document")),
    ("cost per judged document", lambda r: _cost(r, "per_judged_document")),
    ("total cost of the run", lambda r: _cost(r, "total")),
    ("check latency p50 / p95",
     lambda r: f"{_num(r['aggregates']['check_ms_p50'])} / "
     f"{_num(r['aggregates']['check_ms_p95'])} ms"),
    ("errors", lambda r: _rate(r["aggregates"]["error_rate"])),
]


def _column_name(result: dict[str, Any]) -> str:
    meta = result["meta"]
    model = (meta.get("ai") or {}).get("model")
    return f"{meta['config']} ({model})" if model else meta["config"]


def corpus_note(results: list[dict[str, Any]]) -> str:
    """Whether every result was run on the same corpus."""
    hashes = {r["meta"]["corpus_hash"] for r in results}
    if len(hashes) > 1:
        return "WARNING: these results were run on different corpora; the cases are not the same."
    rebuilt = [r["meta"]["config"] for r in results
               if not (r["meta"].get("corpus") or {}).get("files_match_manifest", True)]
    note = f"Same corpus ({next(iter(hashes))[:12]}) in every result."
    if rebuilt:
        note += (f" {', '.join(rebuilt)} rebuilt the files locally with other library versions "
                 "(same ground truth and labels).")
    return note


def table(results: list[dict[str, Any]], *, markdown: bool = False) -> str:
    """The side-by-side table of the main comply metrics."""
    names = [_column_name(r) for r in results]
    rows = [(label, [render(r) for r in results]) for label, render in ROWS]
    if markdown:
        lines = ["| metric | " + " | ".join(names) + " |",
                 "|---|" + "---|" * len(names)]
        lines += [f"| {label} | " + " | ".join(values) + " |" for label, values in rows]
        return "\n".join(lines)
    width = max(len(label) for label, _ in rows) + 2
    columns = [max(len(names[i]), *(len(values[i]) for _, values in rows)) + 2
               for i in range(len(names))]
    lines = [" " * width + "".join(n.ljust(c) for n, c in zip(names, columns, strict=True))]
    for label, values in rows:
        lines.append(label.ljust(width)
                     + "".join(v.ljust(c) for v, c in zip(values, columns, strict=True)))
    return "\n".join(lines)


def _alarm(case: dict[str, Any]) -> bool:
    return any(d.get("severity") in ALARM_SEVERITIES for d in case.get("differences") or [])


def _group(case: dict[str, Any]) -> str:
    label = case["label"]
    if label["mutator"] == "none":
        return "clean"
    return "material" if label["material"] else "benign"


def flips(base: dict[str, Any], other: dict[str, Any]) -> dict[str, list[str]]:
    """Cases whose alarm status differs between two results, by kind of change."""
    before = {c["id"]: c for c in base["cases"] if not c.get("error")}
    changes: dict[str, list[str]] = defaultdict(list)
    for case in other["cases"]:
        old = before.get(case["id"])
        if old is None or case.get("error"):
            continue
        was, now = _alarm(old), _alarm(case)
        if was != now:
            changes[f"{_group(case)}: alarm {'removed' if was else 'added'}"].append(case["id"])
    return dict(sorted(changes.items()))


def report(results: list[dict[str, Any]], *, markdown: bool = False, show: int = 8) -> str:
    """The whole comparison: corpus note, table, and the flipped cases."""
    lines = [corpus_note(results), "", table(results, markdown=markdown)]
    base = results[0]
    for other in results[1:]:
        changes = flips(base, other)
        lines += ["", f"Alarm changes, {_column_name(base)} → {_column_name(other)}:"]
        if not changes:
            lines.append("  none")
        for kind, ids in changes.items():
            more = f" … and {len(ids) - show} more" if len(ids) > show else ""
            lines.append(f"  {kind}: {len(ids)} — {', '.join(ids[:show])}{more}")
    return "\n".join(lines)
