"""Unit tests for the Phase-0 agentic core: tiered config, token usage/cost,
the tool-use loop, and the deterministic normaliser tools."""

from __future__ import annotations

from pydantic import BaseModel

from docforge.ai import pricing
from docforge.ai.client import LLMClient, _ToolsUnsupported
from docforge.ai.tools import ToolSpec, normalizer_tools
from docforge.ai.usage import record_usage, track_usage
from docforge.settings_store import AIConfig


class _Out(BaseModel):
    answer: str


def _cfg(**kw) -> AIConfig:
    base = dict(provider="openai", enabled=True, base_url="http://x", api_key="k", model="m")
    base.update(kw)
    return AIConfig(**base)


# --- pricing ---------------------------------------------------------------

def test_pricing_exact_prefix_and_unknown():
    assert pricing.price_for("gemini-2.5-flash-lite") == (0.10, 0.40)
    # dated/preview suffix resolves via longest known prefix
    assert pricing.price_for("gemini-2.5-flash-lite-preview-09-2025") == (0.10, 0.40)
    assert pricing.price_for("totally-unknown-model") is None
    assert pricing.price_for(None) is None


def test_estimate_cost_and_by_model():
    assert pricing.estimate_cost("gemini-2.5-flash-lite", 1_000_000, 1_000_000) == round(0.10 + 0.40, 6)
    assert pricing.estimate_cost("unknown", 10, 10) is None
    mixed = {"gemini-2.5-flash-lite": {"in": 1_000_000, "out": 0}, "unknown": {"in": 5, "out": 5}}
    # unknown contributes 0, known contributes its share -> not None
    assert pricing.cost_for_by_model(mixed) == 0.10
    assert pricing.cost_for_by_model({"unknown": {"in": 1, "out": 1}}) is None


# --- usage accounting ------------------------------------------------------

def test_usage_accumulates_and_costs():
    with track_usage() as u:
        record_usage("gemini-2.5-flash-lite", 100, 50)
        record_usage("gemini-2.5-flash-lite", 200, 25)
    d = u.as_dict()
    assert d["in"] == 300 and d["out"] == 75 and d["calls"] == 2
    assert d["by_model"]["gemini-2.5-flash-lite"] == {"in": 300, "out": 75, "calls": 2}
    assert d["cost_usd"] is not None


def test_record_usage_without_scope_is_noop():
    # No active accumulator -> must not raise.
    record_usage("m", 1, 1)


# --- tiered model selection ------------------------------------------------

def test_model_for_tier_and_for_tier():
    c = _cfg(reasoning_model="big")
    assert c.model_for_tier("workhorse") == "m"
    assert c.model_for_tier("reasoning") == "big"
    assert _cfg().model_for_tier("reasoning") == "m"  # falls back to workhorse

    client = LLMClient(_cfg(reasoning_model="big"))
    assert client.for_tier("reasoning").model == "big"
    assert client.for_tier("workhorse") is client  # same model -> same instance


# --- agentic loop ----------------------------------------------------------

def test_agentic_falls_back_without_tools(monkeypatch):
    client = LLMClient(_cfg(base_url="http://nofallbacktools"))
    monkeypatch.setattr(client, "complete", lambda msgs, **kw: '{"answer": "hi"}')
    out = client.complete_agentic(system="s", developer="d", user="u", schema=_Out)
    assert out.answer == "hi"


def test_agentic_tool_loop_runs_tool_then_answers(monkeypatch):
    client = LLMClient(_cfg(base_url="http://toolloop"))
    calls = {"n": 0}

    def fake_chat(messages, tool_specs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "content": "",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "echo", "arguments": '{"text": "x"}'}}
                ],
            }
        return {"content": '{"answer": "done"}'}

    monkeypatch.setattr(client, "_chat_step", fake_chat)
    ran: dict = {}

    def _echo(args):
        ran["got"] = args.get("text")
        return {"echo": args.get("text")}

    tools = [
        ToolSpec(
            name="echo",
            description="echo back",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
            func=_echo,
        )
    ]
    out = client.complete_agentic(system="s", developer="d", user="u", schema=_Out, tools=tools)
    assert out.answer == "done"
    assert ran["got"] == "x"
    assert calls["n"] == 2


def test_agentic_tools_unsupported_falls_back(monkeypatch):
    client = LLMClient(_cfg(base_url="http://notools"))

    def boom(messages, tool_specs):
        raise _ToolsUnsupported("no tools here")

    monkeypatch.setattr(client, "_chat_step", boom)
    monkeypatch.setattr(client, "complete", lambda msgs, **kw: '{"answer": "fallback"}')
    out = client.complete_agentic(
        system="s", developer="d", user="u", schema=_Out, tools=normalizer_tools()
    )
    assert out.answer == "fallback"


# --- transient-error retry + tier fallback ---------------------------------

def test_post_with_retry_recovers_from_503(monkeypatch):
    from docforge.ai import client as mod

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    statuses = iter([503, 200])

    class FakeResp:
        def __init__(self, status):
            self.status_code = status
            self.headers = {}
            self.text = "overloaded"
            self.reason_phrase = "err"
        def json(self):
            return {"error": {"message": "overloaded"}}

    class FakeClient:
        def post(self, path, json=None, headers=None):
            return FakeResp(next(statuses))

    resp = mod._post_with_retry(FakeClient(), "chat/completions", {}, {})
    assert resp.status_code == 200


def test_post_with_retry_raises_unavailable_when_exhausted(monkeypatch):
    import pytest

    from docforge.ai import client as mod
    from docforge.ai.client import LLMUnavailable

    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    class FakeResp:
        status_code = 503
        headers: dict = {}
        text = "overloaded"
        reason_phrase = "Service Unavailable"
        def json(self):
            return {"error": {"message": "high demand"}}

    class FakeClient:
        def post(self, path, json=None, headers=None):
            return FakeResp()

    with pytest.raises(LLMUnavailable):
        mod._post_with_retry(FakeClient(), "chat/completions", {}, {})


def test_agentic_reasoning_unavailable_falls_back_to_workhorse(monkeypatch):
    from docforge.ai.client import LLMUnavailable

    client = LLMClient(_cfg(base_url="http://tierfb", reasoning_model="big"))
    used_models: list[str] = []

    def fake_tiered(self, *, tier, **kw):
        used_models.append(self.config.model_for_tier(tier))
        if tier == "reasoning":
            raise LLMUnavailable("503 overloaded")
        return _Out(answer="from-workhorse")

    monkeypatch.setattr(LLMClient, "_complete_agentic_tiered", fake_tiered)
    out = client.complete_agentic(system="s", developer="d", user="u", schema=_Out, tier="reasoning")
    assert out.answer == "from-workhorse"
    assert used_models == ["big", "m"]


def test_agentic_unavailable_workhorse_propagates(monkeypatch):
    import pytest

    from docforge.ai.client import LLMUnavailable

    client = LLMClient(_cfg(base_url="http://tierfb2"))

    def fake_tiered(self, **kw):
        raise LLMUnavailable("503 overloaded")

    monkeypatch.setattr(LLMClient, "_complete_agentic_tiered", fake_tiered)
    with pytest.raises(LLMUnavailable):
        client.complete_agentic(system="s", developer="d", user="u", schema=_Out)


# --- deterministic tools ---------------------------------------------------

def test_normalizer_tools():
    tools = {t.name: t for t in normalizer_tools()}
    assert tools["normalize_date"].run({"text": "June 1 2026"})["iso"] == "2026-06-01"
    assert tools["normalize_number"].run({"text": "$5,000.00"})["number"] == "5000"
    assert tools["normalize_number"].run({"text": "no digits"})["ok"] is False
    assert tools["detect_kind"].run({"text": "2026-06-01"})["kind"] == "date"
    # OpenAI tool schema shape
    schema = tools["normalize_date"].openai_schema()
    assert schema["type"] == "function" and schema["function"]["name"] == "normalize_date"
