"""``python -m evals run --suite analyze`` end to end, without AI and against a fake LM Studio.

The fake classifier makes the invoice number a field and every other element boilerplate, so
the result shows one field found, the rest missed, and every fixed block kept. The fake
read-through and self-critique add nothing. No network.
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
NODE = re.compile(r'"node_id": "(n\\d+)",\\s*"type": "([^"]*)",\\s*"style": "[^"]*",'
                  r'\\s*"text": "([^"]*)"')
def fake(transport, request):
    if request.method == "GET":  # LM Studio's model list
        return httpx.Response(200, request=request, json={"data": [
            {"id": "fake-qwen", "type": "llm", "state": "loaded",
             "max_context_length": 32768, "loaded_context_length": 32768}]})
    posts.append(request)
    body = json.loads(request.content)
    prompt = "\\n".join(m.get("content") or "" for m in body["messages"]
                       if isinstance(m.get("content"), str))
    if '"likely_dynamic"' in prompt:  # pass A, the read-through
        answer = {"document_type": "invoice", "summary": "", "sections": [],
                  "likely_dynamic": []}
    elif '"corrections"' in prompt:  # pass C, the self-critique
        answer = {"corrections": []}
    else:  # pass B, classification
        rows = []
        for node, kind, text in NODE.findall(prompt):
            if text.startswith("Invoice Number: "):
                rows.append({"node_id": node, "classification": "DYNAMIC_TEXT",
                             "field_name": "invoice_number", "field_type": "text",
                             "static_prefix": "Invoice Number: ", "confidence": 0.9})
            else:
                rows.append({"node_id": node, "classification": "FIXED", "confidence": 0.9})
        answer = {"document_type_guess": "invoice", "classifications": rows, "sections": []}
    return httpx.Response(200, request=request, json={
        "choices": [{"message": {"role": "assistant", "content": json.dumps(answer)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 150}})
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
    command = [sys.executable, "-c", DRIVER, "run", "--suite", "analyze",
               "--cache-dir", str(tmp_path / "cache"), "--out", str(tmp_path / "results"), *args]
    done = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                          timeout=600)
    posts = next((int(line.split()[1]) for line in done.stdout.splitlines()
                  if line.startswith("FAKE_POSTS")), -1)
    return done.returncode, done.stdout + done.stderr, posts


def _result(tmp_path, config: str) -> dict:
    [path] = list((tmp_path / "results").glob(f"*_{config}_analyze.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_ai_analyze_builds_a_template_per_number_of_examples(tmp_path):
    code, output, posts = _cli(tmp_path, "--config", "evals/configs/no-ai.yaml",
                               "--types", "invoice_en", "status_report_en")
    assert code == 0, output
    assert posts == 0 and "skipping section toggle" not in output  # DocForge's warnings: kept
    result = _result(tmp_path, "no-ai")
    cases = {case["id"]: case for case in result["cases"]}
    assert list(cases) == [f"invoice_en/k{k}" for k in (1, 2, 3, 5)] + ["invoice_en/shared"] + [
        f"status_report_en/k{k}" for k in (1, 2, 3, 5)] + ["status_report_en/shared"]
    one, two = cases["invoice_en/k1"], cases["invoice_en/k2"]
    assert (one["k"], one["documents"], two["documents"]) == (1, ["ex_01"], ["ex_01", "ex_02"])
    assert one["source"] == two["source"] == "heuristic"
    assert one["outcomes"]["clause.payment"]["outcome"] == "became_field"  # no diff to tell
    assert {o["outcome"] for o in two["outcomes"].values()} <= {"kept", "found", "detected",
                                                              "auto"}
    shared = cases["invoice_en/shared"]
    assert (shared["group"], shared["documents"]) == ("shared", ["ex_01", "shared_02"])
    assert shared["outcomes"]["field.customer"]["outcome"] == "missed"  # identical in both
    report = cases["status_report_en/k1"], cases["status_report_en/k2"]
    assert [r["outcomes"]["info.project"]["outcome"] for r in report] == ["frozen", "looped"]
    assert report[1]["layout"]["problems"] == ["info.project: rows lost"]
    assert any("section toggle" in w for w in cases["status_report_en/k2"]["warnings"])
    by_k = result["aggregates"]["by_k"]
    assert by_k["1"]["cases"] == by_k["5"]["cases"] == 2
    assert result["aggregates"]["shared"]["shared_field_found"]["num"] == 0
    meta = result["meta"]
    assert meta["suite"] == "analyze" and meta["types"] == ["invoice_en", "status_report_en"]
    assert len(meta["analyze_hash"]) == 64 and meta["corpus_hash"].startswith("d2f7d14ee960")


def test_local_analyze_scores_the_ai_classifier_and_replays_from_the_cache(tmp_path):
    args = ("--config", "evals/configs/local.yaml", "--types", "invoice_en", "--limit", "2",
            "--repeat", "2", "--sample", "1")
    code, output, posts = _cli(tmp_path, *args)
    assert code == 0, output
    assert posts >= 4  # the read-through and the classification, for each of the two cases
    result = _result(tmp_path, "local")
    one, two = result["cases"]
    assert one["source"] == two["source"] == "llm"
    assert one["outcomes"]["field.invoice_no"]["outcome"] == "found"
    assert one["outcomes"]["field.invoice_date"]["outcome"] == "missed"
    assert one["outcomes"]["clause.payment"]["outcome"] == "kept"
    assert one["layout"]["preserved"], one["layout"]
    kinds = {call["kind"] for call in one["ai_calls"]}
    assert {"LLMUnderstanding", "LLMClassifyResponse"} <= kinds
    assert all(call["outcome"] == "ok" for call in one["ai_calls"])
    ai = result["aggregates"]["ai"]
    assert ai["fallback_rate"]["num"] == 0 and ai["stability"]["cases"] == 1
    assert len(result["repeats"]) == 1

    code, output, posts = _cli(tmp_path, *args)  # same run again: everything is cached
    assert code == 0, output
    assert posts == 0, f"{posts} calls went to the model on a fully cached rerun"
    again = _result(tmp_path, "local")
    assert again["meta"]["cache_hit_rate"] == 1.0
    assert again["aggregates"]["by_k"] == result["aggregates"]["by_k"]


def test_analyze_dry_run_lists_the_templates_to_build(tmp_path):
    shutil.rmtree(tmp_path / "results", ignore_errors=True)
    code, output, posts = _cli(tmp_path, "--config", "evals/configs/local.yaml", "--dry-run")
    assert code == 0, output
    assert "templates to build        45 (9 types)" in output
    assert "cases that call a model   45" in output
    assert posts == 0 and not (tmp_path / "results").exists()


def test_all_suites_at_once_is_refused(tmp_path):
    code, output, _posts = subprocess_run_all(tmp_path)
    assert code == 2 and "one suite at a time" in output


def subprocess_run_all(tmp_path) -> tuple[int, str, int]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "evals", "run", "--suite", "all", "--config",
                           "evals/configs/no-ai.yaml", "--out", str(tmp_path / "results")],
                          cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr, 0
