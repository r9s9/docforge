"""The response cache: key rules, record and replay, and replay through DocForge's real AI paths.

No test touches the network. Each one replaces the transport's real ``handle_request`` with a
fake *before* installing the cache, so the cache wraps the fake exactly as it would wrap the
network, and the fake counts how often the "network" was used.
"""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from evals import scope
from evals.cache import ResponseCache, canonical_body

httpx2 = pytest.importorskip("httpx2")


class FakeNetwork:
    """Stands in for a transport's real handle_request; records every request it gets."""

    def __init__(self, module, *, status=200, headers=None, body=b'{"ok": true}'):
        self.module, self.status, self.headers, self.body = module, status, headers, body
        self.requests: list = []

    def __call__(self, transport, request):
        self.requests.append(request)
        return self.module.Response(
            self.status,
            headers=self.headers or {"content-type": "application/json"},
            content=self.body,
            request=request,
        )


@pytest.fixture
def network(monkeypatch, tmp_path):
    """Fake networks for httpx and httpx2, with a cache installed on top of them."""
    fakes = {}
    for module in (httpx, httpx2):
        fakes[module.__name__] = FakeNetwork(module)
        monkeypatch.setattr(module.HTTPTransport, "handle_request", fakes[module.__name__])
    cache = ResponseCache(tmp_path / "cache", "test-config")
    cache.install()
    yield cache, fakes
    cache.uninstall()


# --- key rules -------------------------------------------------------------------------------


def test_canonical_body_ignores_key_order_and_masks_ids():
    a = canonical_body(b'{"b": 1, "a": "doc 0123456789abcdef0123456789abcdef"}')
    b = canonical_body(b'{"a": "doc fedcba9876543210fedcba9876543210", "b": 1}')
    assert a == b and "<id>" in a
    assert canonical_body(b'{"b": 2}') != canonical_body(b'{"b": 1}')
    assert canonical_body(b"not json") == "not json"


def test_key_depends_on_config_case_repeat_and_body_but_not_headers(tmp_path):
    cache, other = ResponseCache(tmp_path, "a"), ResponseCache(tmp_path, "b")

    def request(body: bytes, key: str = "secret-1") -> httpx.Request:
        return httpx.Request("POST", "https://api.example.test/v1/messages", content=body,
                             headers={"x-api-key": key})

    with scope.case("case-1"):
        base = cache.key(request(b'{"x": 1}'))
        assert cache.key(request(b'{"x": 1}', key="secret-2")) == base
        assert cache.key(request(b'{"x": 2}')) != base
        assert other.key(request(b'{"x": 1}')) != base
    with scope.case("case-2"):
        assert cache.key(request(b'{"x": 1}')) != base
    with scope.case("case-1", repeat=1):
        assert cache.key(request(b'{"x": 1}')) != base


# --- record and replay -----------------------------------------------------------------------


@pytest.mark.parametrize("module_name", ["httpx", "httpx2"])
def test_a_second_identical_call_is_served_from_the_cache(network, module_name):
    cache, fakes = network
    module = {"httpx": httpx, "httpx2": httpx2}[module_name]
    with scope.case("case-1"), module.Client() as client:
        first = client.post("https://api.example.test/v1/chat", json={"q": 1})
        assert cache.last_call_live() is True
        second = client.post("https://api.example.test/v1/chat", json={"q": 1})
        assert cache.last_call_live() is False
    assert first.json() == second.json() == {"ok": True}
    assert len(fakes[module_name].requests) == 1
    stats = cache.stats("case-1")
    assert (stats.live_calls, stats.replayed_calls) == (1, 1)


def test_refresh_always_calls_the_network_and_rerecords(network, tmp_path):
    cache, fakes = network
    with scope.case("case-1"), httpx.Client() as client:
        client.post("https://api.example.test/v1/chat", json={"q": 1})
        client.post("https://api.example.test/v1/chat", json={"q": 1})
    assert len(fakes["httpx"].requests) == 1  # recorded, then replayed

    cache.uninstall()
    fresh = ResponseCache(tmp_path / "cache", "test-config", refresh=True)  # --no-cache
    fresh.install()
    try:
        fakes["httpx"].body = b'{"ok": "newer"}'
        with scope.case("case-1"), httpx.Client() as client:
            assert client.post("https://api.example.test/v1/chat", json={"q": 1}).json() == {
                "ok": "newer"
            }
    finally:
        fresh.uninstall()
        cache.install()  # the fixture uninstalls it at the end
    assert len(fakes["httpx"].requests) == 2
    with scope.case("case-1"), httpx.Client() as client:  # the re-recorded answer replays
        assert client.post("https://api.example.test/v1/chat", json={"q": 1}).json() == {
            "ok": "newer"
        }
    assert len(fakes["httpx"].requests) == 2


def test_failed_responses_are_not_stored(network):
    cache, fakes = network
    fakes["httpx"].status = 503
    with scope.case("case-1"), httpx.Client() as client:
        assert client.post("https://api.example.test/v1/chat", json={"q": 1}).status_code == 503
        fakes["httpx"].status = 200
        assert client.post("https://api.example.test/v1/chat", json={"q": 1}).status_code == 200
    assert len(fakes["httpx"].requests) == 2  # the 503 wasn't replayed


def test_only_harmless_headers_are_kept_and_compressed_bodies_are_decoded(network):
    cache, fakes = network
    fakes["httpx"].headers = {
        "content-type": "application/json",
        "content-encoding": "gzip",
        "anthropic-organization-id": "org-should-not-be-stored",
        "request-id": "req-1",
    }
    fakes["httpx"].body = gzip.compress(b'{"ok": "decoded"}')
    with scope.case("case-1"), httpx.Client() as client:
        assert client.post("https://api.example.test/v1/chat", json={"q": 1}).json() == {
            "ok": "decoded"
        }
        assert client.post("https://api.example.test/v1/chat", json={"q": 1}).json() == {
            "ok": "decoded"
        }
    [stored] = list(cache.dir.rglob("*.json.gz"))
    entry = json.loads(gzip.decompress(stored.read_bytes()))
    assert entry["headers"] == [["content-type", "application/json"]]


def test_get_requests_pass_straight_through(network):
    cache, fakes = network
    with scope.case("case-1"), httpx.Client() as client:
        client.get("https://api.example.test/v1/models")
        client.get("https://api.example.test/v1/models")
    assert len(fakes["httpx"].requests) == 2
    assert cache.stats("case-1").live_calls == 0


def test_uninstall_restores_the_original_transport(monkeypatch, tmp_path):
    fake = FakeNetwork(httpx)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake)
    cache = ResponseCache(tmp_path, "c")
    cache.install()
    assert httpx.HTTPTransport.handle_request is not fake
    cache.uninstall()
    assert httpx.HTTPTransport.handle_request is fake


# --- contract tests: DocForge's real AI paths on replayed responses ---------------------------

VERDICTS = {"verdicts": [
    {"index": 0, "material": False, "severity": "info", "rationale": "cosmetic"},
    {"index": 1, "material": True, "severity": "error", "rationale": "clause removed"},
]}


def _report():
    from docforge.schemas.compliance import ComplianceDifference, ComplianceReport

    return ComplianceReport(template_id="t", version=1, differences=[
        ComplianceDifference(kind="changed_fixed", severity="warning", message="Heading changed"),
        ComplianceDifference(kind="missing_fixed", severity="error", message="Clause missing"),
    ])


def _sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


ANTHROPIC_STREAM = _sse([
    {"type": "message_start", "message": {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": json.dumps(VERDICTS)}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
     "usage": {"output_tokens": 85}},
    {"type": "message_stop"},
])

OPENAI_COMPLETION = json.dumps({
    "choices": [{"message": {"role": "assistant", "content": json.dumps(VERDICTS)},
                 "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1400, "completion_tokens": 90},
}).encode()


def _judge_twice(client) -> list:
    from docforge.ai.usage import track_usage
    from docforge.compliance.judge import judge_compliance

    outcomes = []
    for _ in range(2):
        with scope.case("contract"), track_usage() as usage:
            report = judge_compliance(_report(), document_type="NDA", client=client)
        semantic = next(d.score for d in report.dimensions if d.name == "semantic")
        outcomes.append(([d.severity for d in report.differences], semantic, usage.as_dict()))
    return outcomes


def test_claude_answers_replay_through_the_real_anthropic_sdk(network):
    from docforge.ai.client import LLMClient
    from docforge.settings_store import AIConfig

    cache, fakes = network
    fakes["httpx2"].headers = {"content-type": "text/event-stream"}
    fakes["httpx2"].body = ANTHROPIC_STREAM
    client = LLMClient(AIConfig(provider="anthropic", enabled=True, api_key="sk-ant-test",
                                base_url="https://api.anthropic.com", model="claude-haiku-5-5"))
    first, second = _judge_twice(client)
    assert first[:2] == second[:2] == (["info", "error"], 50.0)
    assert (first[2]["in"], first[2]["out"]) == (second[2]["in"], second[2]["out"]) == (1200, 85)
    assert first[2]["cost_usd"] == second[2]["cost_usd"] > 0
    assert len(fakes["httpx2"].requests) == 1  # the second judge call never left the process
    assert fakes["httpx2"].requests[0].url.path == "/v1/messages"
    stats = cache.stats("contract")
    assert (stats.live_calls, stats.replayed_calls) == (1, 1)


def test_local_model_answers_replay_through_the_openai_compatible_path(network):
    from docforge.ai.client import LLMClient
    from docforge.settings_store import AIConfig

    cache, fakes = network
    fakes["httpx"].body = OPENAI_COMPLETION
    client = LLMClient(AIConfig(provider="openai", enabled=True, api_key="local",
                                base_url="http://127.0.0.1:1234/v1", model="qwen-test",
                                no_think=True))
    first, second = _judge_twice(client)
    assert first[:2] == second[:2] == (["info", "error"], 50.0)
    assert (first[2]["in"], first[2]["out"]) == (1400, 90)
    assert first[2]["cost_usd"] is None  # a local model has no price: "$0 (hardware)"
    [request] = fakes["httpx"].requests
    assert request.url.path == "/v1/chat/completions"
    sent = json.loads(request.content)
    assert sent["messages"][0]["content"].startswith("/no_think")  # thinking off reached Qwen
    assert cache.stats("contract").replayed_calls == 1
