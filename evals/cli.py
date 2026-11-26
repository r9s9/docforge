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


def _run(args: argparse.Namespace) -> int:
    import time

    from evals.harness import ai_enabled, apply_config, load_config, prepare
    from evals.paths import BUILD_DIR, RESULTS_DIR

    if args.suite != "comply":
        print(f"The {args.suite} suite arrives in M3/M4; only comply runs in M1.", file=sys.stderr)
        return 2
    config = load_config(args.config)
    if ai_enabled(config):  # removed once the budget guard exists (M2, commit 3)
        print("AI runs are not enabled yet: the budget guard arrives later in M2.", file=sys.stderr)
        return 2
    manifest, corpus = _ensure_corpus()
    if args.types:
        unknown = sorted(set(args.types) - set(manifest["types"]))
        if unknown:
            print(f"Unknown types: {', '.join(unknown)}", file=sys.stderr)
            return 2

    from evals.report import git_state

    git = git_state()  # before anything is written
    sandbox = prepare(keep=args.keep_sandbox)
    try:
        ai = apply_config(config, model=args.model)
        from evals.metrics.comply import summarize
        from evals.report import comply_table, result_document, write_result
        from evals.runners import comply

        started = time.perf_counter()
        records, templates = comply.run(manifest, BUILD_DIR, types=args.types, limit=args.limit)
        result = result_document(
            suite="comply", config=config, ai=ai, manifest=manifest, records=records,
            aggregates=summarize(records), templates=templates,
            seconds=time.perf_counter() - started, git=git,
        )
        result["meta"]["corpus"] = corpus
        path = write_result(result, args.out or RESULTS_DIR)
    finally:
        sandbox.close()
    print(comply_table(result))
    print(f"\nResult written to {path}")
    if args.keep_sandbox:
        print(f"Sandbox kept at {sandbox.root}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "corpus":
        return _corpus_build(args)
    if args.command == "run":
        return _run(args)
    return 2
