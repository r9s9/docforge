"""``python -m evals run`` works end to end on a small slice of the corpus.

Runs in a subprocess (DocForge reads its settings once per process) and writes its result to a
temp directory, never to ``evals/results``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from evals.corpus.build import load_manifest
from evals.paths import MANIFEST_PATH, REPO_ROOT, RESULTS_DIR


def test_comply_run_on_three_invoice_cases(tmp_path):
    results_before = sorted(RESULTS_DIR.glob("*.json")) if RESULTS_DIR.exists() else []
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    command = [
        sys.executable, "-m", "evals", "run", "--suite", "comply",
        "--config", "evals/configs/no-ai.yaml", "--types", "invoice_en", "--limit", "3",
        "--out", str(tmp_path),
    ]
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "material deviations found" in done.stdout

    [path] = list(tmp_path.glob("*_no-ai_comply.json"))
    result = json.loads(path.read_text(encoding="utf-8"))
    meta = result["meta"]
    assert meta["cases"] == 3 and meta["config"] == "no-ai" and meta["types"] == ["invoice_en"]
    assert meta["corpus_hash"] == load_manifest(MANIFEST_PATH)["corpus_hash"]
    assert meta["spend_usd"] == {"live": 0.0, "replayed": 0.0}
    assert result["templates"]["invoice_en"]["classification_mismatches"] == []
    assert all(case["error"] is None for case in result["cases"])
    assert (sorted(RESULTS_DIR.glob("*.json")) if RESULTS_DIR.exists() else []) == results_before
