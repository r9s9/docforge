"""The generated results page and README block (``python -m evals report``)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from evals.paths import REPO_ROOT
from evals.report import (
    README_END,
    README_START,
    newest_results,
    readme_block,
    results_page,
    with_block,
)


def _result(config: str, suite: str, date: str, *, model: str | None = None,
            cache_hit_rate: float | None = None) -> dict:
    from evals.metrics.analyze import summarize as analyze
    from evals.metrics.comply import summarize as comply
    from evals.metrics.generate import summarize as generate

    aggregates = {"comply": comply, "generate": generate, "analyze": analyze}[suite]([])
    return {"meta": {"suite": suite, "config": config, "date": date, "docforge_version": "0.21.0",
                     "git_sha": "abcdef1234", "corpus_hash": "c" * 64, "platform": "Linux",
                     "python": "3.11.9", "cache_hit_rate": cache_hit_rate,
                     "ai": {"enabled": model is not None, "model": model}},
            "aggregates": aggregates, "cases": []}


def _write(folder, name: str, result: dict) -> None:
    (folder / name).write_text(json.dumps(result), encoding="utf-8")


def test_the_newest_result_of_each_mode_and_suite_in_a_fixed_order(tmp_path):
    _write(tmp_path, "2026-11-26_local_comply.json", _result("local", "comply", "2026-11-26",
                                                            model="qwen"))
    _write(tmp_path, "2026-11-25_no-ai_comply.json", _result("no-ai", "comply", "2026-11-25"))
    _write(tmp_path, "2026-11-26_no-ai_comply.json", _result("no-ai", "comply", "2026-11-26"))
    _write(tmp_path, "2026-11-26_haiku_analyze.json", _result("haiku", "analyze", "2026-11-26",
                                                             model="claude-haiku-5-5"))
    newest = newest_results(tmp_path)
    assert list(newest) == ["comply", "analyze"]
    assert [path.name for path, _r in newest["comply"]] == [
        "2026-11-26_no-ai_comply.json", "2026-11-26_local_comply.json"]  # no-ai first


def test_the_page_links_each_column_to_its_file_and_marks_a_replayed_latency(tmp_path):
    _write(tmp_path, "2026-11-28_no-ai_analyze.json", _result("no-ai", "analyze", "2026-11-28"))
    _write(tmp_path, "2026-11-28_haiku_analyze.json",
           _result("haiku", "analyze", "2026-11-28", model="claude-haiku-5-5",
                   cache_hit_rate=1.0))
    page = results_page(newest_results(tmp_path), None)
    assert page.startswith("# DocForge evaluation results")
    assert "## Analyze: building a template from examples" in page
    assert "[no-ai](results/2026-11-28_no-ai_analyze.json)" in page
    assert "[haiku (claude-haiku-5-5)](results/2026-11-28_haiku_analyze.json)" in page
    latency = next(line for line in page.splitlines() if line.startswith("| analyze latency"))
    assert latency.count("(replayed)") == 1  # only the result replayed from the cache
    assert results_page(newest_results(tmp_path), None) == page  # nothing time-dependent


def test_the_readme_block_replaces_only_what_sits_between_its_markers(tmp_path):
    _write(tmp_path, "2026-11-26_no-ai_comply.json", _result("no-ai", "comply", "2026-11-26"))
    block = readme_block(newest_results(tmp_path))
    assert block.startswith(README_START) and block.endswith(README_END)
    assert "| | no AI |" in block
    readme = f"# Title\n\nBefore.\n\n{README_START}\nSTALE-TABLE\n{README_END}\n\nAfter.\n"
    updated = with_block(readme, block)
    assert updated.startswith("# Title\n\nBefore.\n\n") and updated.endswith("\n\nAfter.\n")
    assert "STALE-TABLE" not in updated and with_block(updated, block) == updated
    with pytest.raises(ValueError, match="no results block"):
        with_block("# A README without the markers\n", block)


def test_the_committed_page_and_readme_block_are_up_to_date():
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "evals", "report", "--check"], cwd=REPO_ROOT,
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, ("evals/RESULTS.md or the README's results block is stale: "
                                  "run `python -m evals report`\n" + done.stderr)
