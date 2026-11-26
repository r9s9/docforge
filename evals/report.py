"""Result files and the console table.

A result file records what was run and on what: the git SHA (and whether the tree had
uncommitted changes), DocForge's version, the config, the corpus hash and the case count. With
those, any number can be traced back and reproduced. Numbers are only ever written from a run,
never by hand.
"""

from __future__ import annotations

import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals import jsonfmt
from evals.paths import REPO_ROOT


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    """The commit a run was made from, and whether the working tree had changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {"git_sha": None, "dirty": None}
    return {"git_sha": sha, "dirty": bool(status.strip())}


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
            "models": {},
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
    path.write_text(jsonfmt.dumps(result) + "\n", encoding="utf-8")
    return path


def _rate(r: dict[str, Any] | None) -> str:
    if not r or r["value"] is None:
        return "—"
    return f"{r['value']:.2f} ({r['num']}/{r['den']})"


def _num(value: float | None, digits: int = 2, unit: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{unit}"


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
        f"fix success (material)        {_rate(agg['fix_success'])}"
        f"   text {_rate(agg['fix_text_restored'])} · style {_rate(agg['fix_style_restored'])}"
        f" · recheck {_rate(agg['fix_recheck_clean'])} · values {_rate(agg['fix_values_kept'])}",
        f"check_document latency        p50 {_num(agg['check_ms_p50'], 0, ' ms')}"
        f" · p95 {_num(agg['check_ms_p95'], 0, ' ms')}",
        f"errors                        {_rate(agg['error_rate'])}",
        f"templates vs ground truth     "
        f"{len(result['templates']) - len(mismatched)}/{len(result['templates'])} classified "
        f"as intended" + (f" (mismatches: {', '.join(mismatched)})" if mismatched else ""),
    ]
    return "\n".join(lines)
