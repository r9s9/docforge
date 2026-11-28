"""The commands CI runs: ``corpus check`` and ``run --suite all`` (M5)."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

from evals.corpus.build import manifest_differences
from evals.paths import MANIFEST_PATH, REPO_ROOT


def _cli(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("DOCFORGE_") and k != "ANTHROPIC_API_KEY"}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-m", "evals", *args], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True, timeout=timeout)


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_differences_ignore_bytes_but_name_truth_and_label_changes():
    committed = _manifest()
    assert manifest_differences(committed, copy.deepcopy(committed)) == []
    rebuilt = copy.deepcopy(committed)
    for info in rebuilt["types"].values():
        for document in info["documents"].values():
            document["content_hash"] = "0" * 64  # another lxml: other bytes, same content
    assert manifest_differences(committed, rebuilt) == []
    changed = copy.deepcopy(committed)
    changed["types"]["nda_en"]["documents"]["ex_01"]["truth_hash"] = "f" * 64
    changed["analyze"]["shared"]["dpia_en"]["values"]["dpo"] = "Someone Else"
    first = changed["cases"][0]
    first["label"] = {**first["label"], "material": not first["label"]["material"]}
    del changed["cases"][1]
    assert manifest_differences(committed, changed) == [  # sorted by type, then document
        "document dpia_en/shared_02: ground truth or values changed",
        "document nda_en/ex_01: ground truth or values changed",
        f"case {committed['cases'][0]['id']}: base or label changed",
        f"case {committed['cases'][1]['id']}: no longer built",
    ]


def test_corpus_check_passes_on_the_committed_manifest_and_fails_on_a_changed_one(tmp_path):
    done = _cli("corpus", "check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "matches" in done.stdout
    changed = _manifest()
    changed["types"]["nda_en"]["documents"]["ex_01"]["truth_hash"] = "f" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    done = _cli("corpus", "check", "--manifest", str(path))
    assert done.returncode == 1
    assert "document nda_en/ex_01: ground truth or values changed" in done.stderr
    assert "python -m evals corpus build" in done.stderr


def test_run_all_writes_one_result_per_suite_and_gives_each_suite_its_own_types(tmp_path):
    done = _cli("run", "--suite", "all", "--config", "evals/configs/no-ai.yaml",
                "--types", "invoice_en", "dpia_en", "--limit", "1", "--out", str(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr
    results = {path.name.split("_")[2].removesuffix(".json"): json.loads(path.read_text())
               for path in tmp_path.glob("*_no-ai_*.json")}
    assert sorted(results) == ["analyze", "comply", "generate"]
    assert results["comply"]["meta"]["types"] == ["invoice_en"]  # dpia_en is analyze only
    assert results["generate"]["meta"]["types"] == ["invoice_en"]
    assert results["analyze"]["meta"]["types"] == ["dpia_en", "invoice_en"]
    assert [line for line in done.stderr.splitlines() if line.startswith("==")] == [
        "== comply ==", "== generate ==", "== analyze =="]


def test_run_all_refuses_an_unknown_type(tmp_path):
    done = _cli("run", "--suite", "all", "--config", "evals/configs/no-ai.yaml",
                "--types", "nope", "--out", str(tmp_path))
    assert done.returncode == 2 and "Unknown types: nope" in done.stderr
