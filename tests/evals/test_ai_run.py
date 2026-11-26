"""``python -m evals run`` end to end in an AI mode, against a fake LM Studio. No network.

A small driver replaces httpx's transport with a fake server before the CLI starts, so model
detection, the judge's calls, the cache and the observer all run for real on top of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from evals.paths import REPO_ROOT

DRIVER = """
import json, sys
import httpx
posts = []
def fake(transport, request):
    if request.method == "GET":  # LM Studio's model list
        return httpx.Response(200, request=request, json={"data": [
            {"id": "fake-qwen", "type": "llm", "state": "loaded",
             "max_context_length": 32768, "loaded_context_length": 32768}]})
    posts.append(request)
    answer = {"verdicts": [{"index": 0, "material": True, "severity": "error",
                            "rationale": "test"}]}
    return httpx.Response(200, request=request, json={
        "choices": [{"message": {"role": "assistant", "content": json.dumps(answer)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 20}})
httpx.HTTPTransport.handle_request = fake
from evals.cli import main
code = main(sys.argv[1:])
print("FAKE_POSTS", len(posts))
sys.exit(code)
"""


def _cli(tmp_path, *args: str) -> tuple[int, str, int]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("DOCFORGE_") and k != "ANTHROPIC_API_KEY"}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-c", DRIVER, "run", "--suite", "comply",
               "--cache-dir", str(tmp_path / "cache"), "--out", str(tmp_path / "results"), *args]
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          timeout=600)
    posts = next((int(line.split()[1]) for line in done.stdout.splitlines()
                  if line.startswith("FAKE_POSTS")), -1)
    return done.returncode, done.stdout + done.stderr, posts


LOCAL = ("--config", "evals/configs/local.yaml", "--types", "invoice_en")


def test_dry_run_checks_the_setup_and_calls_no_model(tmp_path):
    code, output, posts = _cli(tmp_path, *LOCAL, "--limit", "8", "--dry-run")
    assert code == 0, output
    assert "fake-qwen" in output and "$0 (a local model has no price)" in output
    assert posts == 0
    assert not (tmp_path / "results").exists()


def test_local_run_records_the_judge_then_replays_from_the_cache(tmp_path):
    args = (*LOCAL, "--limit", "16", "--repeat", "2", "--sample", "2")
    code, output, posts = _cli(tmp_path, *args)
    assert code == 0, output
    assert posts > 0
    [path] = list((tmp_path / "results").glob("*_local_comply.json"))
    result = json.loads(path.read_text(encoding="utf-8"))
    meta, ai = result["meta"], result["aggregates"]["ai"]
    assert meta["ai"]["model"] == "fake-qwen" and meta["ai"]["no_think"] is True
    statuses = {case["judge"]["status"] for case in result["cases"]}
    assert {"ran", "not_needed"} <= statuses
    assert ai["judge"]["tp"] + ai["judge"]["fp"] + ai["judge"]["fn"] + ai["judge"]["tn"] > 0
    assert meta["spend_usd"]["live"] == 0.0 and meta["spend_usd"]["unpriced_calls"] > 0
    assert len(result["repeats"]) == 2 and ai["stability"]["cases"] == 2
    assert all(case["fix"] is None for case in result["cases"])  # fixes: no-AI run only
    assert result["aggregates"]["fix_success"]["den"] == 0
    first_posts = posts

    code, output, posts = _cli(tmp_path, *args)  # same run again: everything is cached
    assert code == 0, output
    assert posts == 0, f"{posts} calls went to the model on a fully cached rerun"
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["meta"]["cache_hit_rate"] == 1.0
    assert again["aggregates"]["ai"]["judge"] == result["aggregates"]["ai"]["judge"]
    assert first_posts > 0


def test_haiku_without_a_key_stops_before_anything_runs(tmp_path):
    code, output, posts = _cli(tmp_path, "--config", "evals/configs/haiku.yaml", "--dry-run")
    assert code == 2 and "ANTHROPIC_API_KEY" in output and posts == 0
