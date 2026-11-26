"""Compare results of one suite side by side, and list what changed between them.

``python -m evals compare A.json B.json [C.json ...]`` prints one column per result file and,
for every file after the first, what changed from the first file:
- comply: the cases whose alarm status differs, which is mostly what the AI judge changes (it
  can downgrade a difference to info, or raise one to error)
- generate: the fields whose outcome differs ("omitted → correct", "correct → unsupported")

``--markdown`` prints the table as Markdown for the docs.

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

from evals.metrics.comply import ALARM_SEVERITIES, material_alarms_kept, percentile


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


def _total(result: dict[str, Any]) -> str:
    """Everything the run spent, repeats included (the per-document rows cover one pass)."""
    ai = _ai(result)
    if ai is None:
        return "$0 (no AI)"
    if ai["cost_usd"]["unpriced_calls"] and not ai["cost_usd"]["total"]:
        return "$0 (hardware)"
    spend = result["meta"].get("spend_usd") or {}
    if "live" not in spend:
        return _usd(ai["cost_usd"]["total"])
    return _usd(spend["live"] + spend.get("replayed", 0.0))


def _ok(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [case for case in result["cases"] if not case.get("error")]


def _latency(result: dict[str, Any], *, judged: bool) -> str:
    """p50 / p95 of check_document; ``judged``: only cases with differences (the judge's)."""
    times = [c["check_ms"] for c in _ok(result)
             if c.get("check_ms") is not None and (c.get("differences") or not judged)]
    return f"{_num(percentile(times, 0.50))} / {_num(percentile(times, 0.95))} ms"


def _machine(result: dict[str, Any]) -> str:
    meta = result["meta"]
    if not meta.get("platform"):
        return "n/a"
    return f"{meta['platform']}, Python {meta.get('python', '?')}"


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
    ("total cost, repeats included", _total),
    ("check latency p50 / p95, all cases", lambda r: _latency(r, judged=False)),
    ("check latency p50 / p95, cases with differences", lambda r: _latency(r, judged=True)),
    ("errors", lambda r: _rate(r["aggregates"]["error_rate"])),
    ("run on", _machine),
]


def _gen(result: dict[str, Any], *keys: str) -> Any:
    value: Any = result["aggregates"]
    for key in keys:
        value = (value or {}).get(key)
    return value


def _graded(result: dict[str, Any], question: str, agreement: dict[str, Any] | None) -> str:
    if agreement is not None and not (agreement.get(question) or {}).get("used"):
        return "not graded (grader disagrees with the owner)"
    rated = _gen(result, "free_text", question)
    return _rate(rated) if rated and rated["den"] else "not graded"


def _sources(result: dict[str, Any]) -> str:
    sources = _gen(result, "pipeline", "routing_source") or {}
    return " · ".join(f"{name} {count}" for name, count in sources.items()) or "n/a"


def _grading_cost(result: dict[str, Any]) -> str:
    grader = result["meta"].get("grader") or {}
    if grader.get("status") != "on":
        return "none"
    spent = grader.get("spend_usd") or {}
    return _usd(spent.get("live", 0.0) + spent.get("replayed", 0.0))


def _generate_rows(agreement: dict[str, Any] | None) -> list[tuple[str, Callable]]:
    return [
        ("short fields right", lambda r: _rate(_gen(r, "fields", "accuracy"))),
        ("left empty though given", lambda r: _rate(_gen(r, "fields", "omission_rate"))),
        ("hallucinated", lambda r: _rate(_gen(r, "fields", "hallucination_rate"))),
        ("  of those, flagged as AI-drafted",
         lambda r: _rate(_gen(r, "fields", "hallucinations_flagged"))),
        ("from the notes, but wrong", lambda r: _rate(_gen(r, "fields", "grounded_wrong_rate"))),
        ("empty where the notes are silent",
         lambda r: _rate(_gen(r, "fields", "correctly_empty_rate"))),
        ("a corrected value used", lambda r: str(_gen(r, "fields", "superseded_used"))),
        ("dates and amounts in template form", lambda r: _rate(_gen(r, "fields", "form_kept"))),
        ("table row count right", lambda r: _rate(_gen(r, "tables", "row_count_ok"))),
        ("table cells right", lambda r: _rate(_gen(r, "tables", "cell_accuracy"))),
        ("table cells unsupported", lambda r: _rate(_gen(r, "tables", "unsupported_cells"))),
        ("free text written", lambda r: _rate(_gen(r, "free_text", "written"))),
        ("free text faithful", lambda r: _graded(r, "faithful", agreement)),
        ("free text complete", lambda r: _graded(r, "complete", agreement)),
        ("layout kept", lambda r: _rate(_gen(r, "pipeline", "layout_preserved"))),
        ("written by", _sources),
        ("review led to a rewrite", lambda r: _rate(_gen(r, "pipeline", "rewrites"))),
        ("writer fell back", lambda r: _rate(_ai(r)["fallback_rate"]) if _ai(r) else "n/a"),
        ("stable across repeats",
         lambda r: _rate((_ai(r)["stability"] or {}).get("outcome_agreement"))
         if _ai(r) else "n/a"),
        ("cost per document", lambda r: _cost(r, "per_document")),
        ("total cost, repeats included", _total),
        ("grading cost", _grading_cost),
        ("generate latency p50 / p95",
         lambda r: f"{_num(_gen(r, 'generate_ms_p50'))} / {_num(_gen(r, 'generate_ms_p95'))} ms"),
        ("errors", lambda r: _rate(r["aggregates"]["error_rate"])),
        ("run on", _machine),
    ]


def _by_k(result: dict[str, Any], k: str, key: str) -> Any:
    return result["aggregates"]["by_k"][k][key]


def _f1(r: dict[str, Any] | None) -> str:
    if not r or r.get("value") is None:
        return "n/a"
    return f"{r['value']:.2f} (tp {r['tp']} · fp {r['fp']} · fn {r['fn']})"


def _blocks(counts: dict[str, int]) -> str:
    return " · ".join(f"{outcome} {n}" for outcome, n in counts.items()) or "n/a"


def _analyze_sources(result: dict[str, Any]) -> str:
    return " · ".join(f"{k} {v}" for k, v in result["aggregates"]["sources"].items()) or "n/a"


def _shared(result: dict[str, Any]) -> str:
    shared = result["aggregates"].get("shared")
    return _rate(shared["shared_field_found"]) if shared else "n/a"


def _pooled_type(result: dict[str, Any], group: str, key: str) -> str:
    return _rate(result["aggregates"]["all_examples"][group].get(key))


def _analyze_rows() -> list[tuple[str, Callable]]:
    ks = (("1", "1 example"), ("2", "2 examples"), ("3", "3 examples"), ("5", "5 examples"))
    per_k = (
        ("field F1", lambda r, k: _f1(_by_k(r, k, "field_f1"))),
        ("boilerplate kept", lambda r, k: _rate(_by_k(r, k, "boilerplate_kept"))),
        ("field types right", lambda r, k: _rate(_by_k(r, k, "type_accuracy"))),
        ("tables detected", lambda r, k: _rate(_by_k(r, k, "tables_detected"))),
        ("information blocks", lambda r, k: _blocks(_by_k(r, k, "info_tables"))),
        ("layout kept", lambda r, k: _rate(_by_k(r, k, "layout_preserved"))),
    )
    rows: list[tuple[str, Callable]] = [
        (f"{name}, {label}", lambda r, k=k, render=render: render(r, k))
        for name, render in per_k for k, label in ks
    ]
    return rows + [
        ("shared value still a field (2 examples)", _shared),
        ("amounts typed as numbers", lambda r: _pooled_type(r, "types_by_kind", "money")),
        ("people typed as person", lambda r: _pooled_type(r, "types_by_kind", "person")),
        ("field types right, German", lambda r: _pooled_type(r, "types_by_lang", "de")),
        ("page numbers as auto fields",
         lambda r: _rate(r["aggregates"]["all_examples"]["auto_fields"])),
        ("classified by", _analyze_sources),
        ("fell back to the heuristic",
         lambda r: _rate(_ai(r)["fallback_rate"]) if _ai(r) else "n/a"),
        ("stable across repeats",
         lambda r: _rate((_ai(r)["stability"] or {}).get("outcome_agreement"))
         if _ai(r) else "n/a"),
        ("cost per analysis", lambda r: _cost(r, "per_analysis")),
        ("total cost, repeats included", _total),
        ("analyze latency p50 / p95",
         lambda r: f"{_num(_gen(r, 'analyze_ms_p50'))} / {_num(_gen(r, 'analyze_ms_p95'))} ms"),
        ("errors", lambda r: _rate(r["aggregates"]["error_rate"])),
        ("run on", _machine),
    ]


def rows_for(results: list[dict[str, Any]],
             agreement: dict[str, Any] | None = None) -> list[tuple[str, Callable]]:
    """The table's rows for the results' suite."""
    suites = {r["meta"].get("suite", "comply") for r in results}
    if len(suites) > 1:
        raise ValueError(f"results of different suites can't be compared: {sorted(suites)}")
    if suites == {"generate"}:
        return _generate_rows(agreement)
    return _analyze_rows() if suites == {"analyze"} else ROWS


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
    notes = {r["meta"].get("notes_hash") for r in results}
    if len(notes) > 1:
        return ("WARNING: these results were run on different notes cases; the cases are not "
                "the same.")
    analyze = {r["meta"].get("analyze_hash") for r in results}
    if len(analyze) > 1:
        return ("WARNING: these results were run on different analyze documents; the cases are "
                "not the same.")
    if rebuilt:
        note += (f" {', '.join(rebuilt)} rebuilt the files locally with other library versions "
                 "(same ground truth and labels).")
    return note


def table(results: list[dict[str, Any]], *, markdown: bool = False,
          agreement: dict[str, Any] | None = None) -> str:
    """The side-by-side table of the suite's main metrics."""
    names = [_column_name(r) for r in results]
    rows = [(label, [render(r) for r in results])
            for label, render in rows_for(results, agreement)]
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


def outcome_changes(base: dict[str, Any], other: dict[str, Any]) -> dict[str, list[str]]:
    """Generate: the fields whose outcome differs between two results, by change."""
    before = {c["id"]: c for c in base["cases"] if not c.get("error")}
    changes: dict[str, list[str]] = defaultdict(list)
    for case in other["cases"]:
        old = before.get(case["id"])
        if old is None or case.get("error"):
            continue
        for logical, field in (case.get("fields") or {}).items():
            previous = (old.get("fields") or {}).get(logical)
            if previous and previous["outcome"] != field["outcome"]:
                changes[f"{previous['outcome']} → {field['outcome']}"].append(
                    f"{case['id']} {logical}")
    return dict(sorted(changes.items()))


def element_changes(base: dict[str, Any], other: dict[str, Any]) -> dict[str, list[str]]:
    """Analyze: the elements whose outcome differs between two results, by change."""
    before = {c["id"]: c for c in base["cases"] if not c.get("error")}
    changes: dict[str, list[str]] = defaultdict(list)
    for case in other["cases"]:
        old = before.get(case["id"])
        if old is None or case.get("error"):
            continue
        for logical, outcome in (case.get("outcomes") or {}).items():
            previous = (old.get("outcomes") or {}).get(logical)
            if previous and previous["outcome"] != outcome["outcome"]:
                changes[f"{previous['kind']} {previous['outcome']} → {outcome['outcome']}"].append(
                    f"{case['id']} {logical}")
    return dict(sorted(changes.items()))


def report(results: list[dict[str, Any]], *, markdown: bool = False, show: int = 8,
           agreement: dict[str, Any] | None = None) -> str:
    """The whole comparison: corpus note, table, and what changed."""
    suite = results[0]["meta"].get("suite", "comply")
    lines = [corpus_note(results), "",
             table(results, markdown=markdown,
                   agreement=agreement if suite == "generate" else None)]
    base = results[0]
    changed, what = {
        "generate": (outcome_changes, "Field outcome changes"),
        "analyze": (element_changes, "Element outcome changes"),
    }.get(suite, (flips, "Alarm changes"))
    for other in results[1:]:
        changes = changed(base, other)
        lines += ["", f"{what}, {_column_name(base)} → {_column_name(other)}:"]
        if not changes:
            lines.append("  none")
        for kind, ids in changes.items():
            more = f" … and {len(ids) - show} more" if len(ids) > show else ""
            lines.append(f"  {kind}: {len(ids)} — {', '.join(ids[:show])}{more}")
    return "\n".join(lines)
