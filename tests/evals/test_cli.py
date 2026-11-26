"""The command line parses the commands the brief names (§6.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.cli import build_parser


def test_run_command_parses_suite_and_config():
    args = build_parser().parse_args(
        ["run", "--suite", "comply", "--config", "evals/configs/no-ai.yaml", "--limit", "3"]
    )
    assert args.command == "run"
    assert args.suite == "comply"
    assert args.config == Path("evals/configs/no-ai.yaml")
    assert args.limit == 3


def test_corpus_build_parses():
    args = build_parser().parse_args(["corpus", "build"])
    assert (args.command, args.corpus_command) == ("corpus", "build")


def test_unknown_suite_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--suite", "everything", "--config", "x.yaml"])
