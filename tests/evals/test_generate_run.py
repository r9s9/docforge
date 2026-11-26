"""``python -m evals run --suite generate`` end to end, without AI and against a fake LM Studio.

The fake writer fills two fields of the invoice it is asked for: the invoice number from the
notes (correct), and a VAT ID it makes up and marks as drafted (a flagged hallucination). The
fake reviewer finds nothing. No network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from evals.paths import REPO_ROOT

DRIVER = """
import json, re, sys
import httpx
posts = []
def fake(transport, request):
    if request.method == "GET":  # LM Studio's model list
        return httpx.Response(200, request=request, json={"data": [
            {"id": "fake-qwen", "type": "llm", "state": "loaded",
             "max_context_length": 32768, "loaded_context_length": 32768}]})
    posts.append(request)
    body = json.loads(request.content)
    prompt = "\\n".join(m.get("content") or "" for m in body["messages"]
                       if isinstance(m.get("content"), str))
    if "tools" in body:  # the writer
        names = dict((label.lower(), name) for name, label in re.findall(
            r'"field_name": "([^"]+)",\\s*"label": "([^"]+)"', prompt))
        number = next(v for k, v in names.items() if "number" in k)
        vat = next(v for k, v in names.items() if "vat id" in k)
        answer = {"placements": [
            {"field_name": number, "value": "INV-2026-0157", "source_excerpt": "Invoice Number"},
            {"field_name": vat, "value": "GB999999999", "ai_drafted": True}]}
    else:  # the read-back review
        answer = {"findings": []}
    return httpx.Response(200, request=request, json={
        "choices": [{"message": {"role": "assistant", "content": json.dumps(answer)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60}})
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
    command = [sys.executable, "-c", DRIVER, "run", "--suite", "generate",
               "--cache-dir", str(tmp_path / "cache"), "--out", str(tmp_path / "results"), *args]
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          timeout=600)
    posts = next((int(line.split()[1]) for line in done.stdout.splitlines()
                  if line.startswith("FAKE_POSTS")), -1)
    return done.returncode, done.stdout + done.stderr, posts


def _result(tmp_path, config: str) -> dict:
    [path] = list((tmp_path / "results").glob(f"*_{config}_generate.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_ai_generate_fills_bullet_notes_and_never_calls_a_model(tmp_path):
    code, output, posts = _cli(tmp_path, "--config", "evals/configs/no-ai.yaml",
                               "--types", "invoice_en", "--limit", "2")
    assert code == 0, output
    assert posts == 0 and "not graded (no grader in this run)" in output
    result = _result(tmp_path, "no-ai")
    bullets, email = result["cases"]
    assert (bullets["id"], email["id"]) == ("invoice_en/bullets", "invoice_en/email")
    assert bullets["routing"]["source"] == "heuristic" and bullets["layout"]["preserved"]
    assert {f["outcome"] for f in bullets["fields"].values()} == {"correct"}
    assert result["aggregates"]["fields"]["hallucination_rate"]["num"] == 0
    assert result["meta"]["grader"]["status"] == "off"


def test_local_generate_scores_the_writer_and_replays_from_the_cache(tmp_path):
    args = ("--config", "evals/configs/local.yaml", "--types", "invoice_en", "--limit", "1",
            "--repeat", "2", "--sample", "1")
    code, output, posts = _cli(tmp_path, *args)
    assert code == 0, output
    assert posts >= 2  # the writer and the review, at least
    result = _result(tmp_path, "local")
    [case] = result["cases"]
    assert case["routing"]["source"] == "writer" and case["review"]["ran"] is True
    assert case["fields"]["field.invoice_no"]["outcome"] == "correct"
    vat = case["fields"]["field.vat_id"]
    assert vat["outcome"] == "unsupported" and vat["ai_drafted"] is True
    fields = result["aggregates"]["fields"]
    assert fields["hallucination_rate"]["num"] == 1 and fields["hallucinations_flagged"]["num"] == 1
    assert {call["kind"] for call in case["ai_calls"]} == {"LLMWriteResponse", "LLMRenderReview"}
    assert result["aggregates"]["ai"]["stability"]["cases"] == 1
    assert len(result["repeats"]) == 1

    code, output, posts = _cli(tmp_path, *args)  # same run again: everything is cached
    assert code == 0, output
    assert posts == 0, f"{posts} calls went to the model on a fully cached rerun"
    again = _result(tmp_path, "local")
    assert again["meta"]["cache_hit_rate"] == 1.0
    assert again["aggregates"]["fields"] == result["aggregates"]["fields"]


def test_generate_dry_run_names_the_grader_and_the_cases(tmp_path):
    shutil.rmtree(tmp_path / "results", ignore_errors=True)
    code, output, posts = _cli(tmp_path, "--config", "evals/configs/local.yaml", "--dry-run")
    assert code == 0, output
    assert "free-text grader          off: ANTHROPIC_API_KEY is not set" in output
    assert "notes cases               35 (7 types)" in output
    assert "cases that call a model   35" in output
    assert posts == 0 and not (tmp_path / "results").exists()


FAKE_CLAUDE = '''
import httpx2
graded = []
def fake_claude(transport, request):
    graded.append(request)
    verdict = {"unsupported_claims": [], "faithful": True, "missing_points": [],
               "complete": True}
    return httpx2.Response(200, request=request, json={
        "id": "msg_grade", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": json.dumps(verdict)}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1500, "output_tokens": 120}})
httpx2.HTTPTransport.handle_request = fake_claude
'''
GRADING_DRIVER = DRIVER.replace(
    "httpx.HTTPTransport.handle_request = fake\n",
    "httpx.HTTPTransport.handle_request = fake\n" + FAKE_CLAUDE,
).replace('print("FAKE_POSTS", len(posts))', 'print("FAKE_POSTS", len(posts) + len(graded))')


def test_no_ai_generate_grades_free_text_when_the_key_is_set(tmp_path):
    key = "sk-ant-test-not-a-real-key-0451"
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1", ANTHROPIC_API_KEY=key)
    command = [sys.executable, "-c", GRADING_DRIVER, "run", "--suite", "generate",
               "--config", "evals/configs/no-ai.yaml", "--types", "service_agreement_en",
               "--limit", "1", "--cache-dir", str(tmp_path / "cache"),
               "--out", str(tmp_path / "results")]
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          timeout=600)
    output = done.stdout + done.stderr
    assert done.returncode == 0, output
    assert key not in output
    result = _result(tmp_path, "no-ai")
    [case] = result["cases"]
    assert case["free"]["text.services"]["grade"]["status"] == "graded"
    assert case["grader_spend_usd"]["live"] > 0
    assert result["meta"]["grader"]["status"] == "on"
    assert result["aggregates"]["free_text"]["faithful"]["num"] == 1
    assert key not in json.dumps(result)
