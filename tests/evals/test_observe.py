"""The call observer records each logical AI call once, keeps the judge's verdicts, and splits
spend into live and replayed. Uses DocForge's real client over a fake network."""

from __future__ import annotations

import json

import httpx
import pytest

from evals import scope
from evals.cache import ResponseCache
from evals.observe import CallObserver

VERDICTS = {"verdicts": [
    {"index": 0, "material": True, "severity": "error", "rationale": "cap lowered"},
]}


def _completion(content: str, prompt: int = 1000, completion: int = 50) -> bytes:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }).encode()


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A fake OpenAI-compatible server, the cache over it, and the observer over both."""
    sent: list = []
    state = {"status": 200, "body": _completion(json.dumps(VERDICTS))}

    def fake(transport, request):
        sent.append(request)
        return httpx.Response(state["status"], headers={"content-type": "application/json"},
                              content=state["body"], request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    cache = ResponseCache(tmp_path / "cache", "obs")
    cache.install()
    observer = CallObserver(cache)
    observer.install()
    yield observer, state, sent
    observer.uninstall()
    cache.uninstall()


def _client(model: str = "gpt-4o-mini"):
    from docforge.ai.client import LLMClient
    from docforge.settings_store import AIConfig

    # gpt-4o-mini is in DocForge's price table, so spend has a number to split.
    return LLMClient(AIConfig(provider="openai", enabled=True, api_key="test",
                              base_url="http://127.0.0.1:9/v1", model=model))


def _judge(client):
    from docforge.ai.usage import track_usage
    from docforge.compliance.judge import judge_compliance
    from docforge.schemas.compliance import ComplianceDifference, ComplianceReport

    report = ComplianceReport(template_id="t", version=1, differences=[
        ComplianceDifference(kind="changed_fixed", severity="warning", message="changed")])
    with track_usage():
        return judge_compliance(report, document_type="NDA", client=client)


def test_a_judge_call_is_recorded_once_with_its_verdicts(world):
    observer, _state, _sent = world
    with scope.case("c1"):
        _judge(_client())
    [call] = observer.calls("c1")
    assert (call["kind"], call["method"], call["outcome"], call["tier"]) == (
        "LLMComplianceJudgement", "complete_agentic", "ok", "reasoning"
    )
    assert observer.verdicts("c1") == [[
        {"index": 0, "material": True, "severity": "error", "rationale": "cap lowered"}
    ]]


def test_spend_is_split_into_live_and_replayed(world):
    observer, _state, sent = world
    with scope.case("c1"):
        _judge(_client())
        _judge(_client())  # same request: replayed
    spend = observer.spend("c1")
    assert len(sent) == 1
    assert spend["live"] > 0 and spend["replayed"] == pytest.approx(spend["live"])
    assert observer.total_spend()["live"] == pytest.approx(spend["live"])


def test_an_unpriced_model_is_counted_not_priced(world):
    observer, _state, _sent = world
    with scope.case("c1"):
        _judge(_client(model="qwen-local-test"))
    spend = observer.spend("c1")
    assert (spend["live"], spend["replayed"], spend["unpriced_calls"]) == (0.0, 0.0, 1)


def test_a_call_that_falls_back_internally_counts_once(world):
    from docforge.ai.prompts import LLMComplianceJudgement

    observer, _state, _sent = world
    with scope.case("c2"):
        # No tools: complete_agentic hands the work to complete_json inside.
        _client().complete_agentic(system="s", developer="d", user="u",
                                   schema=LLMComplianceJudgement, tools=None)
    assert [c["method"] for c in observer.calls("c2")] == ["complete_agentic"]


def test_a_failed_call_is_recorded_and_still_raises(world):
    from docforge.ai.errors import LLMError

    observer, state, _sent = world
    state["status"] = 400
    state["body"] = b'{"error": {"message": "bad request"}}'
    with scope.case("c3"), pytest.raises(LLMError):
        _client().complete_json(system="s", developer="d", user="u", schema=dict)
    [call] = observer.calls("c3")
    assert call["outcome"] == "error" and "LLMError" in call["error"]


def test_the_judge_falls_back_quietly_and_the_observer_sees_it(world):
    observer, state, _sent = world
    state["status"] = 400
    state["body"] = b'{"error": {"message": "context length exceeded"}}'
    with scope.case("c4"):
        report = _judge(_client())
    assert all(d.name != "semantic" for d in report.dimensions)  # DocForge kept going
    assert [c["outcome"] for c in observer.calls("c4")] == ["error"]
    assert observer.verdicts("c4") == []


def test_uninstall_restores_docforge(world):
    from docforge.ai.client import LLMClient
    from docforge.ai.usage import Usage

    observer, _state, _sent = world
    wrapped = LLMClient.complete_agentic, Usage.add
    observer.uninstall()
    assert (LLMClient.complete_agentic, Usage.add) != wrapped
    assert not hasattr(LLMClient.complete_agentic, "__wrapped__")
    observer.install()  # the fixture uninstalls it again
