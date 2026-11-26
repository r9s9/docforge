"""Command line for the eval suite: ``python -m evals <command>``.

Imports of DocForge stay inside the command handlers. The sandbox has to set DocForge's
environment before anything imports ``docforge.config`` (see harness.py), so nothing at module
level here may import it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SUITES = ("comply", "generate", "analyze", "all")


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for every subcommand."""
    parser = argparse.ArgumentParser(
        prog="python -m evals", description="DocForge evaluation suite"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("corpus", help="build the test corpus")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)
    build = corpus_sub.add_parser("build", help="build every document and write manifest.json")
    build.add_argument("--out", type=Path, default=None, help="build directory")
    build.add_argument("--manifest", type=Path, default=None, help="manifest path")

    run = sub.add_parser("run", help="run a suite against DocForge")
    run.add_argument("--suite", required=True, choices=SUITES)
    run.add_argument("--config", required=True, type=Path, help="a file in evals/configs/")
    run.add_argument("--types", nargs="+", default=None, help="only these types, e.g. invoice_en")
    run.add_argument("--limit", type=int, default=None, help="at most N cases per type")
    run.add_argument("--out", type=Path, default=None, help="results directory")
    run.add_argument("--keep-sandbox", action="store_true", help="keep the temp directory")
    run.add_argument("--model", default=None, help="override the config's model id")
    run.add_argument("--max-usd", type=float, default=None,
                     help="spending cap in USD (default 3; a config's max_usd can only lower it)")
    run.add_argument("--dry-run", action="store_true",
                     help="check the setup and print the plan and estimate; call no model")
    run.add_argument("--no-cache", action="store_true", help="always call the model live")
    run.add_argument("--repeat", type=int, default=1,
                     help="run a sample of judged cases this many times in total (stability)")
    run.add_argument("--sample", type=int, default=10, help="how many cases --repeat re-runs")
    run.add_argument("--cache-dir", type=Path, default=None, help="response cache directory")

    compare = sub.add_parser("compare", help="compare result files side by side")
    compare.add_argument("results", nargs="+", type=Path, help="two or more result files")
    compare.add_argument("--markdown", action="store_true", help="print a Markdown table")
    return parser


def _corpus_build(args: argparse.Namespace) -> int:
    import time

    from evals.corpus.build import build_corpus, summary
    from evals.paths import BUILD_DIR, MANIFEST_PATH

    started = time.perf_counter()
    manifest = build_corpus(args.out or BUILD_DIR, args.manifest or MANIFEST_PATH)
    print(f"{summary(manifest)} Built in {time.perf_counter() - started:.1f} s.")
    return 0


def _ensure_corpus() -> tuple[dict, dict]:
    """The committed manifest plus a matching build directory (rebuilt if needed).

    Also returns what the run should record about the corpus. If this machine builds files
    whose bytes differ from the manifest's (another python-docx or lxml version) but every
    ground truth and label is the same, the run goes ahead and records both hashes; any other
    difference stops it.
    """
    from evals.corpus.build import build_corpus, load_manifest, same_cases, stale_files
    from evals.paths import BUILD_DIR, MANIFEST_PATH

    manifest = load_manifest(MANIFEST_PATH)
    corpus = {"corpus_hash": manifest["corpus_hash"], "files_match_manifest": True}
    if stale_files(manifest, BUILD_DIR):
        print("Building the corpus first…", file=sys.stderr)
        fresh = build_corpus(BUILD_DIR)
        if fresh["corpus_hash"] != manifest["corpus_hash"]:
            if not same_cases(fresh, manifest):
                raise SystemExit(
                    "The corpus code no longer matches evals/corpus/manifest.json. Run "
                    "`python -m evals corpus build` and commit the manifest before running a "
                    "suite."
                )
            print(
                "Note: this machine builds the corpus files with different bytes (library "
                "versions), but every document's ground truth and every label match the "
                "manifest. The run goes ahead and records both hashes.",
                file=sys.stderr,
            )
            corpus = {
                "corpus_hash": manifest["corpus_hash"],
                "local_corpus_hash": fresh["corpus_hash"],
                "files_match_manifest": False,
            }
            manifest = {**manifest, "types": fresh["types"], "cases": fresh["cases"]}
    return manifest, corpus


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}" if value < 0.1 else f"${value:.2f}"


def _plan_budget(config: dict, args: argparse.Namespace, selected: list[dict], cache) -> dict:
    """Cap, cases the judge will see, how many are cached, and the estimated cost."""
    from evals import budget
    from evals.paths import RESULTS_DIR

    ids = {case["id"] for case in selected}
    judged_all = budget.judged_case_ids(budget.latest_result(RESULTS_DIR, "no-ai", "comply"))
    judged = judged_all & ids if judged_all is not None else None
    cached = set() if args.no_cache else {c for c in (judged or ids) if cache.is_complete(c)}
    per_case = budget.cost_per_judged_case(
        budget.latest_result(RESULTS_DIR, config["name"], "comply")
    )
    # --repeat judges a sample again: at most `sample` cases, `repeat - 1` more times each.
    repeat_calls = (max(args.repeat, 1) - 1) * max(min(args.sample, len(judged)), 0) \
        if judged is not None else 0
    estimate = budget.estimate(judged, cached, per_case)
    if estimate is not None:
        estimate += repeat_calls * per_case  # counted as uncached: an upper bound
    return {
        "cap_usd": budget.effective_cap(config, args.max_usd),
        "judged_expected": len(judged) if judged is not None else None,
        "repeat_calls": repeat_calls,
        "cached": len(cached),
        "cost_per_judged_case": per_case,
        "estimate_usd": estimate,
    }


def _dry_run_text(config: dict, ai: dict, selected: list[dict], plan: dict | None) -> str:
    types = sorted({case["pair"] for case in selected})
    lines = [f"Dry run: {config['name']} · comply — nothing is sent to a model."]
    if ai.get("enabled"):
        served = ai.get("served") or {}
        detail = ", ".join(f"{k} {v}" for k, v in served.items() if k != "id")
        lines.append(f"  model                     {ai['model']} on {ai['host']}"
                     + (f" ({detail})" if detail else ""))
        if ai.get("temperature_sent") is False:
            lines.append("  temperature               not sent: this model takes no sampling "
                         "parameters, so repeated runs can differ")
        context = served.get("loaded_context_length") or served.get("max_context_length")
        if context and int(context) < 16000:
            lines.append(f"  WARNING                   context {context} tokens; load the model "
                         "with at least 16k, or long judge prompts will fail")
    else:
        lines.append("  model                     none (AI off)")
    lines.append(f"  cases to check            {len(selected)} ({len(types)} types)")
    if plan:
        judged = plan["judged_expected"]
        lines.append("  cases the judge will see  "
                     + (f"{judged} (from the no-AI result)" if judged is not None else "unknown"))
        if plan.get("repeat_calls"):
            lines.append(f"  repeat judge calls        {plan['repeat_calls']} (stability)")
        local = ai.get("host", "").startswith(("127.0.0.1", "localhost"))
        lines.append(f"  already in the cache      {plan['cached']}")
        lines.append("  spending cap              "
                     + ("none needed" if local else _money(plan["cap_usd"])))
        if local:
            lines.append("  estimated cost            $0 (a local model has no price)")
        elif plan["estimate_usd"] is not None:
            lines.append(f"  estimated cost            {_money(plan['estimate_usd'])}")
        else:
            lines.append("  estimated cost            unknown: no earlier run of this config. The "
                         "first 3 judged cases are a pilot; the run stops if they project past "
                         "the cap.")
    return "\n".join(lines)


def _progress(record: dict, done: int, total: int) -> None:
    status = (record.get("judge") or {}).get("status") or ""
    seconds = (record.get("check_ms") or 0) / 1000
    line = f"[{done:>3}/{total}] {record['id']:<56} {status:<10} {seconds:6.1f} s"
    if record.get("error"):
        line += f"  ERROR {record['error'][:70]}"
    print(line, file=sys.stderr, flush=True)


def _run(args: argparse.Namespace) -> int:
    import time

    from evals.corpus.build import select_cases
    from evals.harness import ConfigError, ai_enabled, apply_config, load_config, prepare
    from evals.paths import BUILD_DIR, CACHE_DIR, RESULTS_DIR

    if args.suite != "comply":
        print(f"The {args.suite} suite arrives in M3/M4; only comply runs so far.", file=sys.stderr)
        return 2
    config = load_config(args.config)
    ai = ai_enabled(config)
    manifest, corpus = _ensure_corpus()
    if args.types:
        unknown = sorted(set(args.types) - set(manifest["types"]))
        if unknown:
            print(f"Unknown types: {', '.join(unknown)}", file=sys.stderr)
            return 2
    selected = select_cases(manifest, args.types, args.limit)

    from evals.report import git_state

    git = git_state()  # before anything is written
    sandbox = prepare(keep=args.keep_sandbox)
    cache = observer = None
    try:
        try:
            description = apply_config(config, model=args.model)
        except ConfigError as exc:
            print(f"Can't start: {exc}", file=sys.stderr)
            return 2
        plan = None
        if ai:
            from evals.cache import ResponseCache

            cache = ResponseCache(args.cache_dir or CACHE_DIR, config["name"],
                                  refresh=args.no_cache)
            plan = _plan_budget(config, args, selected, cache)
        if args.dry_run:
            print(_dry_run_text(config, description, selected, plan))
            return 0
        if plan and plan["estimate_usd"] is not None and plan["estimate_usd"] > plan["cap_usd"]:
            print(f"Estimated {_money(plan['estimate_usd'])} is above the "
                  f"{_money(plan['cap_usd'])} cap; not starting.", file=sys.stderr)
            return 2

        from evals import budget
        from evals.metrics.comply import summarize
        from evals.observe import CallObserver
        from evals.report import comply_table, result_document, write_result
        from evals.runners import comply

        should_stop = None
        if ai:
            cache.install()
            observer = CallObserver(cache)
            observer.install()
            judged_total = (plan["judged_expected"] or len(selected)) + plan["repeat_calls"]

            def should_stop(rows: list[dict]) -> str | None:
                done = sum(1 for r in rows
                           if (r.get("judge") or {}).get("status") in ("ran", "failed"))
                return budget.stop_reason(observer.total_spend()["live"], plan["cap_usd"], done,
                                          judged_total,
                                          have_estimate=plan["estimate_usd"] is not None)

        started = time.perf_counter()
        outcome = comply.run(
            manifest, BUILD_DIR, types=args.types, limit=args.limit, ai=ai, cache=cache,
            observer=observer, should_stop=should_stop, repeat=args.repeat if ai else 1,
            sample=args.sample, progress=_progress if ai else None,
        )
        result = result_document(
            suite="comply", config=config, ai=description, manifest=manifest,
            records=outcome["records"],
            aggregates=summarize(outcome["records"], outcome["repeats"]),
            templates=outcome["templates"], seconds=time.perf_counter() - started, git=git,
        )
        meta = result["meta"]
        meta["corpus"] = corpus
        meta["stopped"] = outcome["stopped"]
        if ai:
            totals = cache.totals()
            calls = totals.live_calls + totals.replayed_calls
            meta["spend_usd"] = observer.total_spend()
            meta["cache_hit_rate"] = totals.replayed_calls / calls if calls else None
            meta["budget"] = plan
        result["repeats"] = outcome["repeats"]
        path = write_result(result, args.out or RESULTS_DIR)
    finally:
        if observer is not None:
            observer.uninstall()
        if cache is not None:
            cache.uninstall()
        sandbox.close()
    print(comply_table(result))
    if meta["stopped"]:
        print(f"\nSTOPPED EARLY ({meta['stopped']}): live spend reached the cap or the pilot "
              "projected past it. The result holds the cases checked so far.")
    print(f"\nResult written to {path}")
    if args.keep_sandbox:
        print(f"Sandbox kept at {sandbox.root}")
    return 0


def _compare(args: argparse.Namespace) -> int:
    from evals.compare import load, report

    if len(args.results) < 2:
        print("Give two or more result files to compare.", file=sys.stderr)
        return 2
    print(report([load(path) for path in args.results], markdown=args.markdown))
    return 0


def _tolerant_output() -> None:
    """Show characters the output can't encode as ``?`` instead of failing.

    On Windows, output that is piped or redirected uses the ANSI code page (cp1252, say), which
    has no ``→``. Printing the table must not crash a run whose result file is already written.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    _tolerant_output()
    args = build_parser().parse_args(argv)
    if args.command == "corpus":
        return _corpus_build(args)
    if args.command == "run":
        return _run(args)
    if args.command == "compare":
        return _compare(args)
    return 2
