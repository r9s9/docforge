"""Result files, the console tables, and the generated results page.

A result file records what was run and on what: the git SHA (and whether the tree had
uncommitted changes), DocForge's version, the config, the corpus hash and the case count. With
those, any number can be traced back and reproduced. Numbers are only ever written from a run,
never by hand: ``evals/RESULTS.md`` and the main README's results block are generated from the
result files by ``python -m evals report``.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals import jsonfmt
from evals.paths import REPO_ROOT

# What a run executes or reads. A change anywhere else (an editor's settings, a note file)
# can't change a result. evals/results is left out of the status check altogether.
RUN_CODE = ("backend/", "evals/")


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    """The commit a run was made from, and what in the working tree differed from it.

    - ``dirty``: any uncommitted change. Result files don't count: a second run before the first
      one's result is committed still ran the committed code.
    - ``dirty_code``: a change under ``backend/`` or ``evals/``, which a run executes or reads.
    - ``changed_files``: the tracked files that differ. Untracked files are only counted
      (``untracked_files``): their names are the owner's business, and result files are public.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--", ".", ":(exclude)evals/results"],
            cwd=repo, capture_output=True, check=True,
        ).stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return {"git_sha": None, "dirty": None, "dirty_code": None, "changed_files": None,
                "untracked_files": None}
    tracked: list[str] = []
    untracked: list[str] = []
    entries = iter(status.split("\0"))
    for entry in entries:
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            next(entries, None)  # a rename or copy is followed by its original path
        (untracked if code == "??" else tracked).append(path)
    return {
        "git_sha": sha,
        "dirty": bool(tracked or untracked),
        "dirty_code": any(path.startswith(RUN_CODE) for path in tracked + untracked),
        "changed_files": sorted(tracked),
        "untracked_files": len(untracked),
    }


def library_versions() -> dict[str, str | None]:
    """Versions of the libraries that shape the corpus files and the model calls."""
    from importlib import metadata

    versions: dict[str, str | None] = {}
    for name in ("python-docx", "lxml", "anthropic", "httpx", "httpx2"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def result_document(
    *,
    suite: str,
    config: dict[str, Any],
    ai: dict[str, Any],
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    aggregates: dict[str, Any],
    templates: dict[str, Any],
    seconds: float,
    git: dict[str, Any],
) -> dict[str, Any]:
    """Everything a run produced, in the shape DESIGN.md §7 describes."""
    import docforge

    return {
        "meta": {
            "suite": suite,
            "config": config["name"],
            "ai": ai,
            "models": {"model": ai.get("model")} if ai.get("enabled") else {},
            "date": datetime.now(UTC).date().isoformat(),
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **git,
            "docforge_version": docforge.__version__,
            "corpus_hash": manifest["corpus_hash"],
            "cases": len(records),
            "types": sorted(templates),
            "cache_hit_rate": None,
            "spend_usd": {"live": 0.0, "replayed": 0.0},
            "stopped": None,
            "seconds": round(seconds, 1),
            "python": platform.python_version(),
            "platform": platform.system(),
            "libraries": library_versions(),
        },
        "templates": templates,
        "aggregates": aggregates,
        "cases": records,
    }


def write_result(result: dict[str, Any], out_dir: Path) -> Path:
    """Write ``<date>_<config>_<suite>.json``; a rerun on the same day replaces it."""
    meta = result["meta"]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{meta['date']}_{meta['config']}_{meta['suite']}.json"
    path.write_text(jsonfmt.dumps(result) + "\n", encoding="utf-8", newline="\n")
    return path


def _rate(r: dict[str, Any] | None) -> str:
    if not r or r["value"] is None:
        return "—"
    return f"{r['value']:.2f} ({r['num']}/{r['den']})"


def _num(value: float | None, digits: int = 2, unit: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{unit}"


def _usd(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:.4f}" if value < 0.1 else f"${value:.2f}"


def _ai_lines(meta: dict[str, Any], ai: dict[str, Any]) -> list[str]:
    judge, cost, stable = ai["judge"], ai["cost_usd"], ai["stability"]
    unpriced = cost["unpriced_calls"] and not cost["total"]
    spend = (
        f"$0 (no price for this model: {cost['unpriced_calls']} unpriced calls)"
        if unpriced
        else f"total {_usd(cost['total'])} (live {_usd(cost['live'])}, replayed "
        f"{_usd(cost['replayed'])}) · per document {_usd(cost['per_document'])} · per judged "
        f"document {_usd(cost['per_judged_document'])}"
    )
    failures = " · ".join(f"{kind} {_rate(r)}" for kind, r in ai["ai_call_failures"].items())
    lines = [
        "",
        f"AI judge: {meta['ai'].get('model')} on {meta['ai'].get('host')}",
        f"  verdicts: material precision {_rate(judge['precision'])} · recall "
        f"{_rate(judge['recall'])} · accuracy {_rate(judge['accuracy'])} · not judged "
        f"{judge['not_judged']}",
        f"  judge fell back to no verdict {_rate(ai['judge_fallback_rate'])}",
        f"  semantic AUC clean > material {_num(ai['semantic_auc_clean_vs_material'])}",
        f"  material still alarming after the judge {_rate(ai['material_alarms_kept'])}",
        f"  cost {spend}",
        f"  cache hit rate {_num(meta.get('cache_hit_rate'))}",
        f"  failed AI calls by kind: {failures or '—'}",
    ]
    if stable:
        lines.append(
            f"  stability: verdicts agree {_rate(stable['verdict_agreement'])} over "
            f"{stable['cases']} cases × {stable['runs_per_case']} runs · semantic spread "
            f"{_num(stable['semantic_spread_mean'])}"
        )
    return lines


def comply_table(result: dict[str, Any]) -> str:
    """The console summary of a comply run."""
    meta, agg = result["meta"], result["aggregates"]
    lines = [
        f"DocForge evals · comply · {meta['config']} · {meta['cases']} cases · "
        f"{len(meta['types'])} types · corpus {meta['corpus_hash'][:12]} · {meta['seconds']} s",
        "",
        f"{'mutator':22} {'expected kind':15} {'material':8} {'n':>4} {'found':>7} "
        f"{'kind ok':>7} {'alarms':>7} {'score':>6}",
    ]
    rows = sorted(agg["by_mutator"], key=lambda r: (r["mutator"] == "none", not r["material"],
                                                    r["mutator"]))
    for row in rows:
        clean = row["mutator"] == "none"
        name = "clean control" if clean else row["mutator"]
        kind_ok = "—" if clean or not row["expected_kind"] else str(row["kind_ok"])
        lines.append(
            f"{name:22} {(row['expected_kind'] or '—'):15} "
            f"{('—' if clean else 'yes' if row['material'] else 'no'):8} {row['n']:>4} "
            f"{('—' if clean else str(row['found'])):>7} {kind_ok:>7} {row['alarms']:>7} "
            f"{row['mean_score']:>6.1f}"
        )
    by_kind = " · ".join(f"{k} {_rate(v)}" for k, v in agg["detection_by_kind"].items())
    mismatched = [p for p, t in result["templates"].items() if t["classification_mismatches"]]
    lines += [
        "",
        f"material deviations found     {_rate(agg['detection_recall'])}",
        f"  by expected kind            {by_kind}",
        f"kind accuracy (when found)    {_rate(agg['kind_accuracy'])}",
        f"benign changes that alarm     {_rate(agg['benign_alarm_rate'])}",
        f"clean controls that alarm     {_rate(agg['false_alarm_rate_clean'])}"
        f"   mean alarms per clean doc {_num(agg['mean_alarms_clean'])}",
        f"spurious differences / case   {_num(agg['spurious_per_mutated_case'])}",
        f"score AUC clean > material    {_num(agg['score_auc_clean_vs_material'])}",
        (
            f"fix success (material)        {_rate(agg['fix_success'])}"
            f"   text {_rate(agg['fix_text_restored'])} · style "
            f"{_rate(agg['fix_style_restored'])} · recheck {_rate(agg['fix_recheck_clean'])}"
            f" · values {_rate(agg['fix_values_kept'])}"
            if agg["fix_success"]["den"]
            else "fix success (material)        n/a (measured in the no-AI run)"
        ),
        f"check_document latency        p50 {_num(agg['check_ms_p50'], 0, ' ms')}"
        f" · p95 {_num(agg['check_ms_p95'], 0, ' ms')}",
        f"errors                        {_rate(agg['error_rate'])}",
        f"templates vs ground truth     "
        f"{len(result['templates']) - len(mismatched)}/{len(result['templates'])} classified "
        f"as intended" + (f" (mismatches: {', '.join(mismatched)})" if mismatched else ""),
    ]
    if agg.get("ai"):
        lines += _ai_lines(meta, agg["ai"])
    return "\n".join(lines)


def generate_table(result: dict[str, Any]) -> str:
    """The console summary of a generate run."""
    meta, agg = result["meta"], result["aggregates"]
    fields, tables, free, pipeline = (agg["fields"], agg["tables"], agg["free_text"],
                                      agg["pipeline"])
    lines = [
        f"DocForge evals · generate · {meta['config']} · {meta['cases']} notes cases · "
        f"{len(meta['types'])} types · {meta['seconds']} s",
        "",
        f"{'notes style':14} {'short fields right':>22} {'hallucinated':>18}",
    ]
    for style, row in agg["by_style"].items():
        lines.append(f"{style:14} {_rate(row['accuracy']):>22} "
                     f"{_rate(row['hallucination_rate']):>18}")
    lines += ["", f"{'kind of field':14} {'right':>22} {'hallucinated':>18}"]
    for kind, row in agg["by_kind"].items():
        lines.append(f"{kind:14} {_rate(row['accuracy']):>22} "
                     f"{_rate(row['hallucination_rate']):>18}")
    outcomes = fields["outcomes"]
    graded = free["graded"]["num"]
    lines += [
        "",
        f"short fields right            {_rate(fields['accuracy'])}",
        f"  left empty though given     {_rate(fields['omission_rate'])}",
        f"  hallucinated                {_rate(fields['hallucination_rate'])}"
        f"   flagged as AI-drafted {_rate(fields['hallucinations_flagged'])}",
        f"  from the notes, but wrong   {_rate(fields['grounded_wrong_rate'])}"
        f"   a corrected value used {fields['superseded_used']}",
        f"  empty where notes are silent {_rate(fields['correctly_empty_rate'])}"
        f"   placeholders {fields['placeholders']}",
        "  outcomes                    " + " · ".join(f"{k} {v}" for k, v in outcomes.items()),
        f"dates/amounts in template form {_rate(fields['form_kept'])}",
        f"tables: row count right       {_rate(tables['row_count_ok'])}   cells right "
        f"{_rate(tables['cell_accuracy'])} · unsupported cells {_rate(tables['unsupported_cells'])}"
        f" · tables invented {_rate(tables['invented_tables'])}",
        f"free text written             {_rate(free['written'])}   left empty though given "
        f"{_rate(free['omitted'])}",
        (f"free text graded              {_rate(free['graded'])}   faithful "
         f"{_rate(free['faithful'])} · complete {_rate(free['complete'])}"
         if graded else "free text graded              not graded (no grader in this run)"),
        f"layout kept                   {_rate(pipeline['layout_preserved'])}",
        "written by                    " + " · ".join(
            f"{k} {v}" for k, v in pipeline["routing_source"].items())
        + f"   review ran {_rate(pipeline['review_ran'])} · rewrites "
          f"{_rate(pipeline['rewrites'])}",
        f"generate latency              p50 {_num(agg['generate_ms_p50'], 0, ' ms')}"
        f" · p95 {_num(agg['generate_ms_p95'], 0, ' ms')}",
        f"errors                        {_rate(agg['error_rate'])}",
    ]
    grader = meta.get("grader") or {}
    if grader.get("status") == "on":
        spent = grader.get("spend_usd") or {}
        lines.append(f"grader                        {grader.get('model')} · spent "
                     f"{_usd(spent.get('live', 0.0))} live, {_usd(spent.get('replayed', 0.0))}"
                     " replayed")
    ai = agg.get("ai")
    if ai:
        cost = ai["cost_usd"]
        unpriced = cost["unpriced_calls"] and not cost["total"]
        failures = " · ".join(f"{kind} {_rate(r)}" for kind, r in ai["ai_call_failures"].items())
        lines += [
            "",
            f"AI: {meta['ai'].get('model')} on {meta['ai'].get('host')}",
            "  cost " + (f"$0 (no price for this model: {cost['unpriced_calls']} unpriced calls)"
                         if unpriced else
                         f"total {_usd(cost['total'])} (live {_usd(cost['live'])}, replayed "
                         f"{_usd(cost['replayed'])}) · per document {_usd(cost['per_document'])}"),
            f"  writer fell back (route or heuristic) {_rate(ai['fallback_rate'])}",
            f"  cache hit rate {_num(meta.get('cache_hit_rate'))}",
            f"  failed AI calls by kind: {failures or '—'}",
        ]
        stable = ai.get("stability")
        if stable:
            lines.append(f"  stability: field outcomes agree {_rate(stable['outcome_agreement'])}"
                         f" · values agree {_rate(stable['value_agreement'])} over "
                         f"{stable['cases']} cases × {stable['runs_per_case']} runs")
    return "\n".join(lines)


def _f1(r: dict[str, Any] | None) -> str:
    if not r or r["value"] is None:
        return "—"
    return f"{r['value']:.2f} (tp {r['tp']} fp {r['fp']} fn {r['fn']})"


def analyze_table(result: dict[str, Any]) -> str:
    """The console summary of an analyze run: quality by number of examples, then the rest."""
    meta, agg = result["meta"], result["aggregates"]
    lines = [
        f"DocForge evals · analyze · {meta['config']} · {meta['cases']} templates · "
        f"{len(meta['types'])} types · {meta['seconds']} s",
        "",
        f"{'examples':9}{'field F1':>27}{'boilerplate kept':>20}{'types right':>16}"
        f"{'tables':>14}{'layout kept':>14}",
    ]
    for k, row in agg["by_k"].items():
        if not row["cases"]:
            continue
        lines.append(f"{k:9}{_f1(row['field_f1']):>27}{_rate(row['boilerplate_kept']):>20}"
                     f"{_rate(row['type_accuracy']):>16}{_rate(row['tables_detected']):>14}"
                     f"{_rate(row['layout_preserved']):>14}")
    pooled = agg["all_examples"]
    blocks = " | ".join(f"{k}: " + (" · ".join(f"{o} {n}" for o, n in row["info_tables"].items())
                                    or "—")
                        for k, row in agg["by_k"].items() if row["cases"])
    lines += [
        "",
        f"information blocks by examples  {blocks}",
        "types right by kind             " + " · ".join(
            f"{kind} {_rate(r)}" for kind, r in pooled["types_by_kind"].items()),
        "types right by language         " + " · ".join(
            f"{lang} {_rate(r)}" for lang, r in pooled["types_by_lang"].items()),
        f"page numbers as auto fields     {_rate(pooled['auto_fields'])}",
    ]
    shared = agg.get("shared")
    if shared:
        missed = ", ".join(shared["missed"]) or "none"
        lines.append(f"shared value still a field      {_rate(shared['shared_field_found'])}"
                     f"   missed: {missed}")
    lines += [
        "classified by                   " + " · ".join(
            f"{k} {v}" for k, v in agg["sources"].items()),
        f"analyze latency                 p50 {_num(agg['analyze_ms_p50'], 0, ' ms')}"
        f" · p95 {_num(agg['analyze_ms_p95'], 0, ' ms')}",
        f"errors                          {_rate(agg['error_rate'])}",
    ]
    ai = agg.get("ai")
    if ai:
        cost = ai["cost_usd"]
        unpriced = cost["unpriced_calls"] and not cost["total"]
        failures = " · ".join(f"{kind} {_rate(r)}" for kind, r in ai["ai_call_failures"].items())
        lines += [
            "",
            f"AI: {meta['ai'].get('model')} on {meta['ai'].get('host')}",
            "  cost " + (f"$0 (no price for this model: {cost['unpriced_calls']} unpriced calls)"
                         if unpriced else
                         f"total {_usd(cost['total'])} (live {_usd(cost['live'])}, replayed "
                         f"{_usd(cost['replayed'])}) · per analysis "
                         f"{_usd(cost['per_analysis'])}"),
            f"  fell back to the heuristic {_rate(ai['fallback_rate'])}",
            f"  cache hit rate {_num(meta.get('cache_hit_rate'))}",
            f"  failed AI calls by kind: {failures or '—'}",
        ]
        stable = ai.get("stability")
        if stable:
            lines.append(f"  stability: element outcomes agree "
                         f"{_rate(stable['outcome_agreement'])} over {stable['cases']} cases × "
                         f"{stable['runs_per_case']} runs")
    return "\n".join(lines)


# --- the results page and the README block ------------------------------------------------

CONFIG_ORDER = ("no-ai", "haiku", "local")
SUITE_ORDER = ("comply", "generate", "analyze")
SUITE_TITLES = {
    "comply": "Comply: checking a returned document",
    "generate": "Generate: filling a template from rough notes",
    "analyze": "Analyze: building a template from examples",
}
README_START = "<!-- evals:start · generated by `python -m evals report`; don't edit -->"
README_END = "<!-- evals:end -->"


def newest_results(results_dir: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    """The newest result file per suite and config, configs in a fixed order."""
    from evals.compare import load

    newest: dict[tuple[str, str], Path] = {}
    for path in sorted(results_dir.glob("*.json")):  # dated names: the last one is the newest
        _date, config, suite = path.stem.split("_", 2)
        newest[(suite, config)] = path

    def order(config: str) -> tuple[int, str]:
        return (CONFIG_ORDER.index(config) if config in CONFIG_ORDER else len(CONFIG_ORDER),
                config)

    out: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for suite in SUITE_ORDER:
        configs = sorted((c for s, c in newest if s == suite), key=order)
        if configs:
            out[suite] = [(newest[(suite, c)], load(newest[(suite, c)])) for c in configs]
    return out


def _mode(result: dict[str, Any]) -> str:
    meta = result["meta"]
    model = (meta.get("ai") or {}).get("model")
    return f"{meta['config']} ({model})" if model else meta["config"]


def results_page(newest: dict[str, list[tuple[Path, dict[str, Any]]]],
                 agreement: dict[str, Any] | None) -> str:
    """``evals/RESULTS.md``: one section per suite, each table straight from ``compare``."""
    from evals.compare import corpus_note, table

    lines = [
        "# DocForge evaluation results",
        "",
        "<!-- Generated by `python -m evals report` from the files in evals/results/. Don't "
        "edit it by hand: rerun the command. -->",
        "",
        "How well DocForge's three pipelines work, measured by the eval suite on its synthetic "
        "corpus, in every mode that has a committed result. Each column links to the result "
        "file its numbers come from. What a line means: [README](README.md). What each "
        "milestone found and why: [CHANGELOG](CHANGELOG.md).",
    ]
    for suite, pairs in newest.items():
        results = [result for _path, result in pairs]
        headers = [f"[{_mode(result)}](results/{path.name})" for path, result in pairs]
        runs = " · ".join(
            f"{_mode(result)}: {result['meta']['date']}, DocForge "
            f"{result['meta']['docforge_version']}, commit {result['meta']['git_sha'][:7]}"
            for _path, result in pairs)
        lines += ["", f"## {SUITE_TITLES[suite]}", "", f"Runs: {runs}.", "",
                  corpus_note(results)]
        if suite == "generate" and agreement:
            notes = []
            for question in ("faithful", "complete"):
                entry = agreement.get(question) or {}
                share = entry.get("agreement") or {}
                if share.get("den"):
                    used = "used" if entry.get("used") else "not used"
                    notes.append(f"{question} {share['value']:.2f} ({share['num']}/"
                                 f"{share['den']}), {used}")
            if notes:
                lines += ["", "Free-text grades come from the rubric grader, checked against "
                          "the owner's labels: " + "; ".join(notes) + "."]
        lines += ["", table(results, markdown=True,
                            agreement=agreement if suite == "generate" else None,
                            headers=headers)]
    return "\n".join(lines) + "\n"


def _value(result: dict[str, Any] | None, *path: str) -> Any:
    value: Any = result["aggregates"] if result else None
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _cost(result: dict[str, Any] | None, key: str) -> str:
    if result is None:
        return "—"
    ai = result["aggregates"].get("ai")
    if ai is None:
        return "$0"
    cost = ai["cost_usd"]
    if cost["unpriced_calls"] and not cost["total"]:
        return "$0 (hardware)"
    return _usd(cost.get(key))


def readme_block(newest: dict[str, list[tuple[Path, dict[str, Any]]]]) -> str:
    """The main README's results table: a few headline numbers per mode, all three suites."""
    by_config: dict[str, dict[str, dict[str, Any]]] = {}
    for suite, pairs in newest.items():
        for _path, result in pairs:
            by_config.setdefault(result["meta"]["config"], {})[suite] = result
    configs = [c for c in CONFIG_ORDER if c in by_config] + sorted(
        c for c in by_config if c not in CONFIG_ORDER)

    def mode(config: str) -> str:
        result = next(iter(by_config[config].values()))
        return "no AI" if not (result["meta"].get("ai") or {}).get("enabled") else _mode(result)

    def f1(result: dict[str, Any] | None, k: str) -> str:
        entry = _value(result, "by_k", k, "field_f1")
        return "—" if not entry or entry.get("value") is None else f"{entry['value']:.2f}"

    rows = [
        ("Returned documents: material changes found",
         lambda r: _rate(_value(r["comply"], "detection_recall")) if "comply" in r else "—"),
        ("Returned documents: harmless edits flagged as problems",
         lambda r: _rate(_value(r["comply"], "benign_alarm_rate")) if "comply" in r else "—"),
        ("Returned documents: clean ones flagged by mistake",
         lambda r: _rate(_value(r["comply"], "false_alarm_rate_clean"))
         if "comply" in r else "—"),
        ("Rough notes: short fields filled right",
         lambda r: _rate(_value(r["generate"], "fields", "accuracy"))
         if "generate" in r else "—"),
        ("Rough notes: values made up",
         lambda r: _rate(_value(r["generate"], "fields", "hallucination_rate"))
         if "generate" in r else "—"),
        ("New template from 1 example: fields told from fixed text (F1)",
         lambda r: f1(r.get("analyze"), "1")),
        ("New template from 2 examples: the same (F1)", lambda r: f1(r.get("analyze"), "2")),
        ("Cost per document: check · fill · build",
         lambda r: " · ".join([_cost(r.get("comply"), "per_document"),
                               _cost(r.get("generate"), "per_document"),
                               _cost(r.get("analyze"), "per_analysis")])),
    ]
    lines = [README_START, "",
             "| | " + " | ".join(mode(c) for c in configs) + " |",
             "|---|" + "---|" * len(configs)]
    for label, render in rows:
        lines.append(f"| {label} | " + " | ".join(render(by_config[c]) for c in configs) + " |")
    return "\n".join(lines + ["", README_END])


def with_block(readme: str, block: str) -> str:
    """The README with its results block replaced; its markers must be there already."""
    start, end = readme.find(README_START), readme.find(README_END)
    if start < 0 or end < start:
        raise ValueError("the README has no results block (the evals:start and evals:end "
                         "markers)")
    return readme[:start] + block + readme[end + len(README_END):]

