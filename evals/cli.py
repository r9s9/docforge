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
    return parser


def _corpus_build(args: argparse.Namespace) -> int:
    import time

    from evals.corpus.build import build_corpus, summary
    from evals.paths import BUILD_DIR, MANIFEST_PATH

    started = time.perf_counter()
    manifest = build_corpus(args.out or BUILD_DIR, args.manifest or MANIFEST_PATH)
    print(f"{summary(manifest)} Built in {time.perf_counter() - started:.1f} s.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "corpus":
        return _corpus_build(args)
    if args.command == "run":
        print("`run` is not available yet (M1 in progress).", file=sys.stderr)
        return 2
    return 2
