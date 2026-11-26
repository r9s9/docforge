"""The rubric grader through the real Anthropic SDK, against a recorded answer. No network.

As in the cache's contract tests, a fake replaces the SDK transport's ``handle_request`` before
the cache is installed, so the cache wraps the fake as it would wrap the network.
"""

from __future__ import annotations

import json

import pytest

from evals import scope
from evals.cache import ResponseCache
from evals.corpus.notes import load_notes
from evals.graders.rubric import Grader, prompt

httpx2 = pytest.importorskip("httpx2")

CONFIG = {"name": "grader", "provider": "anthropic", "model": "claude-haiku-5-5",
          "effort": "medium", "max_tokens": 4000, "api_key_env": "EVALS_TEST_GRADER_KEY",
          "max_usd": 1.0}
CASE = next(c for c in load_notes(["service_agreement_en"]) if c.style == "email")
POINTS = CASE.expected["text.services"]["points"]
VALUE = "Hosting of the document archive in an EU data centre, with nightly backups."


def _message(verdict: dict, status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps({
        "id": "msg_grade", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": json.dumps(verdict)}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1500, "output_tokens": 120, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
    }).encode()


class FakeAnthropic:
    def __init__(self):
        self.requests: list = []
        self.status, self.body = _message({
            "unsupported_claims": [], "faithful": True,
            "missing_points": ["a restore test every six months"], "complete": False})

    def __call__(self, transport, request):
        self.requests.append(request)
        return httpx2.Response(self.status, headers={"content-type": "application/json"},
                               content=self.body, request=request)


@pytest.fixture
def anthropic_api(monkeypatch, tmp_path):
    monkeypatch.setenv("EVALS_TEST_GRADER_KEY", "sk-ant-test-not-a-real-key")
    fake = FakeAnthropic()
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", fake)
    cache = ResponseCache(tmp_path / "cache", "grader-test")
    cache.install()
    yield cache, fake
    cache.uninstall()


def test_a_grade_replays_through_the_real_sdk_and_its_cost_is_counted(anthropic_api):
    cache, fake = anthropic_api
    grader = Grader(CONFIG, cache=cache)
    with scope.case(CASE.id):
        first = grader(CASE, "text.services", VALUE, POINTS)
        second = grader(CASE, "text.services", VALUE, POINTS)
    assert first["status"] == second["status"] == "graded"
    assert first["faithful"] is True and first["complete"] is False
    assert first["missing_points"] == ["a restore test every six months"]
    cost = (1500 * 0.10 + 120 * 0.50) / 1_000_000  # DocForge's Haiku 5.5 price per 1M tokens
    assert first["spend_usd"] == {"live": pytest.approx(cost), "replayed": 0.0}
    assert second["spend_usd"] == {"live": 0.0, "replayed": pytest.approx(cost)}
    assert grader.spent == {"live": pytest.approx(cost), "replayed": pytest.approx(cost)}
    assert len(fake.requests) == 1  # the second grade never left the process

    request = fake.requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/messages" and body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in body
    user = body["messages"][0]["content"]
    assert CASE.text.strip() in user and VALUE in user and POINTS[0] in user


def test_without_expected_points_only_faithfulness_counts(anthropic_api):
    cache, fake = anthropic_api
    fake.status, fake.body = _message({"unsupported_claims": ["monthly reporting"],
                                       "faithful": True, "missing_points": [], "complete": True})
    with scope.case(CASE.id):
        grade = Grader(CONFIG, cache=cache)(CASE, "text.services", VALUE, None)
    assert grade["complete"] is None and grade["missing_points"] == []
    assert grade["faithful"] is False  # a listed unsupported claim outweighs "faithful: true"
    assert "The notes give nothing for this field" in prompt(CASE, "text.services", VALUE, None)


def test_an_api_error_is_a_failed_grade_not_a_crash(anthropic_api):
    cache, fake = anthropic_api
    fake.status = 400
    fake.body = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                                                       "message": "bad request"}}).encode()
    with scope.case(CASE.id):
        grade = Grader(CONFIG, cache=cache)(CASE, "text.services", VALUE, POINTS)
    assert grade["status"] == "failed" and "BadRequestError" in grade["error"]


def test_the_grader_is_available_only_when_its_key_is_set(monkeypatch):
    monkeypatch.delenv("EVALS_TEST_GRADER_KEY", raising=False)
    assert Grader.available(CONFIG) is False
    monkeypatch.setenv("EVALS_TEST_GRADER_KEY", "   ")
    assert Grader.available(CONFIG) is False
    monkeypatch.setenv("EVALS_TEST_GRADER_KEY", "sk-ant-test")
    assert Grader.available(CONFIG) is True


def test_the_prompt_names_the_document_and_the_field():
    text = prompt(CASE, "text.services", VALUE, POINTS)
    assert text.startswith("Document type: service agreement, written in English.")
    assert "Field: services" in text and "<expected_points>\n- " in text
