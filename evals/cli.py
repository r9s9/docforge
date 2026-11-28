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
    corpus_check = corpus_sub.add_parser(
        "check", help="rebuild the corpus in a temp folder and compare it with the manifest")
    corpus_check.add_argument("--manifest", type=Path, default=None, help="manifest path")

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
    run.add_argument("--no-grade", action="store_true",
                     help="generate: don't grade free-text fields")
    run.add_argument("--grader", type=Path, default=None,
                     help="generate: the grader config (default evals/configs/grader.yaml)")

    labels = sub.add_parser("labels", help="the owner's labels for the free-text grader")
    labels_sub = labels.add_subparsers(dest="labels_command", required=True)
    sheet = labels_sub.add_parser("sheet", help="pick the 30 items to label from generate results")
    sheet.add_argument("results", nargs="*", type=Path,
                       help="generate result files (default: the newest of each config)")
    sheet.add_argument("--languages", nargs="+", default=None,
                       help="only items whose document and notes are in these languages, "
                            "e.g. en (mixed-language notes are left out)")
    check = labels_sub.add_parser("check", help="how often the grader agrees with the labels")
    check.add_argument("results", nargs="*", type=Path,
                       help="generate result files (default: the newest of each config)")

    rescore = sub.add_parser("rescore", help="recompute generate outcomes with today's metrics")
    rescore.add_argument("results", nargs="+", type=Path, help="generate result files")

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


def _corpus_check(args: argparse.Namespace) -> int:
    """Whether the corpus code still builds what the committed manifest says (CI's first step).

    Fails when a document's ground truth or values, or a case's label, differ. Files whose bytes
    alone differ (another python-docx or lxml version) are only noted: the cases are the same.
    """
    import tempfile

    from evals.corpus.build import build_corpus, load_manifest, manifest_differences
    from evals.paths import MANIFEST_PATH

    path = args.manifest or MANIFEST_PATH
    committed = load_manifest(path)
    with tempfile.TemporaryDirectory() as tmp:
        fresh = build_corpus(Path(tmp) / "build")
    if fresh == committed:
        print(f"The corpus matches {path} exactly (corpus {committed['corpus_hash'][:12]}).")
        return 0
    differences = manifest_differences(committed, fresh)
    if differences:
        print(f"The corpus code no longer builds what {path} says:", file=sys.stderr)
        for line in differences[:20]:
            print(f"  {line}", file=sys.stderr)
        if len(differences) > 20:
            print(f"  … and {len(differences) - 20} more", file=sys.stderr)
        print("Run `python -m evals corpus build` and commit the manifest.", file=sys.stderr)
        return 1
    print(f"The corpus matches {path}: every ground truth, value and label is the same. Only the "
          "files' bytes differ, as another python-docx or lxml version writes them.")
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
            manifest = {**manifest, "types": fresh["types"], "cases": fresh["cases"],
                        "analyze": fresh["analyze"]}
    return manifest, corpus


def _money(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}" if value < 0.1 else f"${value:.2f}"


def _case_id(case) -> str:
    return case["id"] if isinstance(case, dict) else case.id


def _case_pair(case) -> str:
    return case["pair"] if isinstance(case, dict) else case.pair


def _plan_budget(config: dict, args: argparse.Namespace, selected: list, cache, *,
                 suite: str = "comply", judged: set[str] | None = None,
                 cap: float | None = None) -> dict:
    """Cap, the cases that will call a model, how many are cached, and the estimated cost.

    For comply, the cases the judge will see come from the latest no-AI result; other suites
    pass ``judged`` themselves.
    """
    from evals import budget
    from evals.paths import RESULTS_DIR

    ids = {_case_id(case) for case in selected}
    if suite == "comply":
        judged_all = budget.judged_case_ids(budget.latest_result(RESULTS_DIR, "no-ai", "comply"))
        judged = judged_all & ids if judged_all is not None else None
    cached = set() if args.no_cache else {c for c in (judged or ids) if cache.is_complete(c)}
    per_case = budget.cost_per_case(budget.latest_result(RESULTS_DIR, config["name"], suite),
                                    suite)
    # --repeat runs a sample again: at most `sample` cases, `repeat - 1` more times each.
    repeat_calls = (max(args.repeat, 1) - 1) * max(min(args.sample, len(judged)), 0) \
        if judged is not None else 0
    estimate = budget.estimate(judged, cached, per_case)
    if estimate is not None:
        estimate += repeat_calls * per_case  # counted as uncached: an upper bound
    return {
        "cap_usd": budget.effective_cap(config, args.max_usd) if cap is None else cap,
        "judged_expected": len(judged) if judged is not None else None,
        "repeat_calls": repeat_calls,
        "cached": len(cached),
        "cost_per_judged_case": per_case,
        "estimate_usd": estimate,
    }


def _dry_run_text(config: dict, ai: dict, selected: list, plan: dict | None, *,
                  suite: str = "comply", grading: str | None = None) -> str:
    types = sorted({_case_pair(case) for case in selected})
    lines = [f"Dry run: {config['name']} · {suite} — nothing is sent to a model."]
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
                         "with at least 16k, or long prompts will fail")
    else:
        lines.append("  model                     none (AI off)")
    if grading is not None:
        lines.append(f"  free-text grader          {grading}")
    noun = {"comply": "cases to check", "generate": "notes cases"}.get(suite, "templates to build")
    lines.append(f"  {noun:<26}{len(selected)} ({len(types)} types)")
    if plan:
        judged = plan["judged_expected"]
        if suite == "comply":
            lines.append("  cases the judge will see  "
                         + (f"{judged} (from the no-AI result)" if judged is not None
                            else "unknown"))
            if plan.get("repeat_calls"):
                lines.append(f"  repeat judge calls        {plan['repeat_calls']} (stability)")
        else:
            lines.append(f"  cases that call a model   {judged}")
            if plan.get("repeat_calls"):
                lines.append(f"  repeat runs               {plan['repeat_calls']} (stability)")
        # A local model costs nothing; the grader (Claude) does, so it brings back the cap.
        grader_on = grading is not None and not grading.startswith("off")
        unpriced = ai.get("host", "").startswith(("127.0.0.1", "localhost")) and not grader_on
        lines.append(f"  already in the cache      {plan['cached']}")
        lines.append("  spending cap              "
                     + ("none needed" if unpriced else _money(plan["cap_usd"])))
        if unpriced:
            lines.append("  estimated cost            $0 (a local model has no price)")
        elif plan["estimate_usd"] is not None:
            lines.append(f"  estimated cost            {_money(plan['estimate_usd'])}")
        else:
            lines.append("  estimated cost            unknown: no earlier run of this config. The "
                         "first 3 cases that call a model are a pilot; the run stops if they "
                         "project past the cap.")
    return "\n".join(lines)


def _progress(record: dict, done: int, total: int) -> None:
    status = ((record.get("judge") or {}).get("status")
              or (record.get("routing") or {}).get("source") or record.get("source") or "")
    ms = next((record[key] for key in ("check_ms", "generate_ms", "analyze_ms") if key in record),
              None)
    seconds = (ms or 0) / 1000
    line = f"[{done:>3}/{total}] {record['id']:<56} {status:<10} {seconds:6.1f} s"
    if record.get("error"):
        line += f"  ERROR {record['error'][:70]}"
    print(line, file=sys.stderr, flush=True)


def _grading(args: argparse.Namespace) -> tuple[dict | None, str]:
    """The grader config, and what the dry run says about it."""
    from evals.graders.rubric import Grader, load_grader_config
    from evals.paths import CONFIGS_DIR

    config = load_grader_config(args.grader or CONFIGS_DIR / "grader.yaml")
    if args.no_grade:
        return None, "off (--no-grade)"
    if not Grader.available(config):
        return None, (f"off: {config['api_key_env']} is not set, so free-text fields are not "
                      "graded")
    return config, f"{config['model']} (grading may spend up to {_money(config['max_usd'])})"


def _suite_command(args: argparse.Namespace, suite: str, types: list[str] | None,
                   max_usd: float | None) -> list[str]:
    """The ``python -m evals run`` command for one suite of ``--suite all``."""
    command = [sys.executable, "-m", "evals", "run", "--suite", suite, "--config",
               str(args.config), "--repeat", str(args.repeat), "--sample", str(args.sample)]
    for flag, value in (("--limit", args.limit), ("--out", args.out), ("--model", args.model),
                        ("--max-usd", max_usd), ("--cache-dir", args.cache_dir),
                        ("--grader", args.grader)):
        if value is not None:
            command += [flag, str(value)]
    for flag, on in (("--keep-sandbox", args.keep_sandbox), ("--dry-run", args.dry_run),
                     ("--no-cache", args.no_cache), ("--no-grade", args.no_grade)):
        if on:
            command.append(flag)
    if types:
        command += ["--types", *types]
    return command


def _run_all(args: argparse.Namespace) -> int:
    """Every suite in turn, one result file each. With AI, one spending cap covers all three:
    each suite may spend what the earlier ones left.

    Each suite runs in a process of its own, as a run must: the sandbox is set up before
    anything imports DocForge, once per process.
    """
    import subprocess

    from evals import budget
    from evals.corpus.build import all_types, load_manifest
    from evals.harness import ai_enabled, load_config
    from evals.paths import MANIFEST_PATH, RESULTS_DIR

    config = load_config(args.config)
    manifest = load_manifest(MANIFEST_PATH)
    if args.types:
        unknown = sorted(set(args.types) - set(all_types(manifest)))
        if unknown:
            print(f"Unknown types: {', '.join(unknown)}", file=sys.stderr)
            return 2
    cap = budget.effective_cap(config, args.max_usd) if ai_enabled(config) else None
    spent = 0.0
    for suite in ("comply", "generate", "analyze"):
        known = all_types(manifest) if suite == "analyze" else manifest["types"]
        types = [t for t in args.types if t in known] if args.types else None
        if args.types and not types:
            print(f"== {suite}: none of the given types; skipped", file=sys.stderr, flush=True)
            continue
        left = None
        if cap is not None:
            left = round(cap - spent, 6)
            if left <= 0:
                print(f"The {_money(cap)} cap is used up; {suite} was not started.",
                      file=sys.stderr)
                return 2
        print(f"== {suite} ==", file=sys.stderr, flush=True)
        code = subprocess.run(_suite_command(args, suite, types, left)).returncode
        if code:
            return code
        if cap is not None and not args.dry_run:
            result = budget.latest_result(args.out or RESULTS_DIR, config["name"], suite) or {}
            meta = result.get("meta") or {}
            grading = (meta.get("grader") or {}).get("spend_usd") or {}
            spent += (meta.get("spend_usd") or {}).get("live", 0.0) + grading.get("live", 0.0)
    return 0


def _run(args: argparse.Namespace) -> int:
    import time

    from evals.harness import ConfigError, ai_enabled, apply_config, load_config, prepare
    from evals.paths import BUILD_DIR, CACHE_DIR, RESULTS_DIR

    if args.suite == "all":
        return _run_all(args)
    config = load_config(args.config)
    ai = ai_enabled(config)
    manifest, corpus = _ensure_corpus()
    if args.types:
        from evals.corpus.build import all_types

        known = all_types(manifest) if args.suite == "analyze" else manifest["types"]
        unknown = sorted(set(args.types) - set(known))
        if unknown:
            print(f"Unknown types: {', '.join(unknown)}", file=sys.stderr)
            return 2
    grader_config, grading = (None, None)
    if args.suite == "comply":
        from evals.corpus.build import select_cases

        selected = select_cases(manifest, args.types, args.limit)
    elif args.suite == "generate":
        from evals.corpus.notes import load_notes, select_notes

        selected = select_notes(load_notes(), args.types, args.limit)
        grader_config, grading = _grading(args)
    else:
        from evals.corpus.analyze import analyze_cases

        selected = analyze_cases(manifest, args.types, args.limit)
    paid = ai or grader_config is not None

    from evals.report import git_state

    git = git_state()  # before anything is written
    if git["dirty_code"]:
        print(f"Note: backend/ or evals/ has uncommitted changes, so this result won't match "
              f"commit {git['git_sha'][:7]} exactly.", file=sys.stderr)
    sandbox = prepare(keep=args.keep_sandbox)
    cache = observer = grader = None
    try:
        try:
            description = apply_config(config, model=args.model)
        except ConfigError as exc:
            print(f"Can't start: {exc}", file=sys.stderr)
            return 2
        plan = None
        if paid:
            from evals import budget
            from evals.cache import ResponseCache

            cache = ResponseCache(args.cache_dir or CACHE_DIR, config["name"],
                                  refresh=args.no_cache)
            cap = budget.effective_cap(config, args.max_usd)
            judged = None
            if args.suite == "generate":
                if grader_config is not None:
                    cap = min(cap, float(grader_config["max_usd"]))
                judged = {c.id for c in selected if ai or any(
                    e["kind"] == "free" for e in c.expected.values())}
            elif args.suite == "analyze":
                judged = {c.id for c in selected}  # with AI on, every analysis calls it
            plan = _plan_budget(config, args, selected, cache, suite=args.suite, judged=judged,
                                cap=cap)
        if args.dry_run:
            print(_dry_run_text(config, description, selected, plan, suite=args.suite,
                                grading=grading))
            return 0
        if plan and plan["estimate_usd"] is not None and plan["estimate_usd"] > plan["cap_usd"]:
            print(f"Estimated {_money(plan['estimate_usd'])} is above the "
                  f"{_money(plan['cap_usd'])} cap; not starting.", file=sys.stderr)
            return 2

        from evals.observe import CallObserver
        from evals.report import result_document, write_result

        should_stop = None
        if paid:
            cache.install()
            if ai:
                observer = CallObserver(cache)
                observer.install()
            if grader_config is not None:
                from evals.graders.rubric import Grader

                grader = Grader(grader_config, cache=cache)
            judged_total = (plan["judged_expected"] or len(selected)) + plan["repeat_calls"]

            def live_spend() -> float:
                spent = observer.total_spend()["live"] if observer else 0.0
                return spent + (grader.spent["live"] if grader else 0.0)

            def counted(row: dict) -> bool:
                if args.suite == "comply":
                    return (row.get("judge") or {}).get("status") in ("ran", "failed")
                return bool(row.get("ai") or row.get("grader_spend_usd"))

            def should_stop(rows: list[dict]) -> str | None:
                return budget.stop_reason(live_spend(), plan["cap_usd"],
                                          sum(1 for r in rows if counted(r)), judged_total,
                                          have_estimate=plan["estimate_usd"] is not None)

        started = time.perf_counter()
        progress = _progress if paid else None
        if args.suite == "comply":
            from evals.metrics.comply import summarize
            from evals.report import comply_table as table
            from evals.runners import comply

            outcome = comply.run(
                manifest, BUILD_DIR, types=args.types, limit=args.limit, ai=ai, cache=cache,
                observer=observer, should_stop=should_stop, repeat=args.repeat if ai else 1,
                sample=args.sample, progress=progress,
            )
        elif args.suite == "generate":
            from evals.metrics.generate import summarize
            from evals.report import generate_table as table
            from evals.runners import generate

            outcome = generate.run(
                selected, manifest, BUILD_DIR, ai=ai, cache=cache, observer=observer,
                grader=grader, should_stop=should_stop, repeat=args.repeat if ai else 1,
                sample=args.sample, progress=progress,
            )
        else:
            from evals.metrics.analyze import summarize
            from evals.report import analyze_table as table
            from evals.runners import analyze

            outcome = analyze.run(
                selected, manifest, BUILD_DIR, ai=ai, cache=cache, observer=observer,
                should_stop=should_stop, repeat=args.repeat if ai else 1, sample=args.sample,
                progress=progress,
            )
        result = result_document(
            suite=args.suite, config=config, ai=description, manifest=manifest,
            records=outcome["records"],
            aggregates=summarize(outcome["records"], outcome["repeats"]),
            templates=outcome["templates"], seconds=time.perf_counter() - started, git=git,
        )
        meta = result["meta"]
        meta["corpus"] = corpus
        meta["stopped"] = outcome["stopped"]
        if args.suite == "analyze":
            meta["analyze_hash"] = manifest["analyze"]["analyze_hash"]
        if args.suite == "generate":
            from evals.corpus.notes import load_notes, notes_hash

            meta["notes_hash"] = notes_hash(load_notes())
            meta["grader"] = {"status": "on" if grader else "off", "detail": grading,
                              "model": grader_config["model"] if grader else None,
                              "spend_usd": dict(grader.spent) if grader else None}
        if paid:
            totals = cache.totals()
            calls = totals.live_calls + totals.replayed_calls
            meta["spend_usd"] = observer.total_spend() if observer else {
                "live": 0.0, "replayed": 0.0, "unpriced_calls": 0}
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
    print(table(result))
    if meta["stopped"]:
        print(f"\nSTOPPED EARLY ({meta['stopped']}): live spend reached the cap or the pilot "
              "projected past it. The result holds the cases run so far.")
    print(f"\nResult written to {path}")
    if args.keep_sandbox:
        print(f"Sandbox kept at {sandbox.root}")
    return 0


def _compare(args: argparse.Namespace) -> int:
    from evals.compare import load, report
    from evals.graders.labels import AGREEMENT_PATH

    if len(args.results) < 2:
        print("Give two or more result files to compare.", file=sys.stderr)
        return 2
    results = [load(path) for path in args.results]
    agreement = load(AGREEMENT_PATH) if AGREEMENT_PATH.exists() else None
    try:
        print(report(results, markdown=args.markdown, agreement=agreement))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _rescore(args: argparse.Namespace) -> int:
    from evals import jsonfmt
    from evals.compare import load
    from evals.report import git_state
    from evals.rescore import RescoreError, rescore

    git = git_state()
    for path in args.results:
        try:
            result = rescore(load(path), git)
        except RescoreError as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            return 2
        Path(path).write_text(jsonfmt.dumps(result) + "\n", encoding="utf-8", newline="\n")
        print(f"{path}: {result['meta']['rescored'][-1]['outcomes_changed']} outcomes changed")
    return 0


def _newest_generate_results() -> list[Path]:
    from evals.paths import RESULTS_DIR

    newest: dict[str, Path] = {}
    for path in sorted(RESULTS_DIR.glob("*_generate.json")):
        config = path.name.split("_", 1)[1].rsplit("_generate.json", 1)[0]
        newest[config] = path  # sorted by date, so the last one wins
    return [newest[config] for config in sorted(newest)]


def _labels(args: argparse.Namespace) -> int:
    from evals import jsonfmt
    from evals.compare import load
    from evals.graders import labels

    paths = args.results or _newest_generate_results()
    if not paths:
        print("No generate results to take the items from.", file=sys.stderr)
        return 2
    results = [load(path) for path in paths]
    if args.labels_command == "sheet":
        data = labels.sheet(results, languages=tuple(args.languages) if args.languages else None)
        path = labels.write_sheet(data)
        print(f"{len(data['items'])} items from {', '.join(data['results'])} written to {path}")
        return 0
    if not labels.OWNER_PATH.exists():
        print(f"No owner labels yet ({labels.OWNER_PATH}).", file=sys.stderr)
        return 2
    result = labels.agreement(labels.load_json(labels.SHEET_PATH),
                              labels.load_json(labels.OWNER_PATH), results)
    labels.AGREEMENT_PATH.write_text(jsonfmt.dumps(result) + "\n", encoding="utf-8",
                                     newline="\n")
    for question in labels.QUESTIONS:
        agreed = result[question]["agreement"]
        value = "n/a" if agreed["value"] is None else f"{agreed['value']:.2f}"
        verdict = "used" if result[question]["used"] else "not used"
        print(f"{question:9} the grader agrees with the owner on {value} "
              f"({agreed['num']}/{agreed['den']}): {verdict} (gate {result['gate']:.2f})")
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
        return _corpus_check(args) if args.corpus_command == "check" else _corpus_build(args)
    if args.command == "run":
        return _run(args)
    if args.command == "compare":
        return _compare(args)
    if args.command == "labels":
        return _labels(args)
    if args.command == "rescore":
        return _rescore(args)
    return 2
