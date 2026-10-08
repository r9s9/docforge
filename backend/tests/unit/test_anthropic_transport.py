"""Claude through the official SDK: the request shape each model accepts, the
tool loop, structured outputs, refusals, failures, cancellation and cost.

The SDK client is replaced by a fake that records every request and replies
with real ``anthropic.types.Message`` objects, so the code under test parses
exactly what the API would send back.
"""

from __future__ import annotations

import threading

import anthropic
import httpx2
import pytest
from anthropic.types import Message
from pydantic import BaseModel

from docforge.ai import anthropic_transport as at
from docforge.ai import pricing
from docforge.ai.client import LLMClient
from docforge.ai.errors import LLMCancelled, LLMError, LLMRefused, LLMUnavailable
from docforge.ai.prompts import LLMClassifyResponse, LLMWriteResponse, response_schema
from docforge.ai.tools import ToolSpec
from docforge.ai.usage import track_usage
from docforge.settings_store import REASONING_TIER, WORKHORSE_TIER, AIConfig

HAIKU = "claude-haiku-5-5"


def _cfg(**kw) -> AIConfig:
    base = dict(
        provider="anthropic", enabled=True, base_url="https://api.anthropic.com",
        api_key="sk-ant-test", model=HAIKU,
    )
    base.update(kw)
    return AIConfig(**base)


def _message(content, stop_reason="end_turn", usage=None, model=HAIKU, stop_details=None) -> Message:
    return Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "stop_details": stop_details,
        "usage": usage or {"input_tokens": 10, "output_tokens": 5},
    })


def _text(text: str) -> list[dict]:
    return [{"type": "text", "text": text}]


class _Event:
    def __init__(self, text):
        self.type = "text"
        self.text = text
        self.snapshot = text


class _Stream:
    def __init__(self, message, events):
        self._message = message
        self._events = events
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._message

    def close(self):
        self.closed = True


class _Manager:
    def __init__(self, stream):
        self._stream = stream

    def __enter__(self):
        return self._stream

    def __exit__(self, *exc):
        self._stream.close()


class FakeClaude:
    """Replies are messages, or exceptions to raise; requests are recorded."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.streams: list[_Stream] = []
        self.retrieved: list[str] = []
        outer = self

        class _Messages:
            def stream(self, **params):
                outer.requests.append(params)
                reply = outer.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                events = reply.pop("events", []) if isinstance(reply, dict) else []
                message = reply["message"] if isinstance(reply, dict) else reply
                s = _Stream(message, events)
                outer.streams.append(s)
                return _Manager(s)

        class _Models:
            def retrieve(self, model):
                outer.retrieved.append(model)
                if model == "claude-nope":
                    raise _status(anthropic.NotFoundError, 404, "model not found")
                return {"id": model}

        self.messages = _Messages()
        self.models = _Models()


def _status(cls, code, message):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(code, request=request), body=None)


@pytest.fixture(autouse=True)
def _fresh_capabilities():
    at._DROPPED.clear()
    yield
    at._DROPPED.clear()


@pytest.fixture
def fake(monkeypatch):
    holder: dict = {}

    def install(*replies):
        claude = FakeClaude(replies)
        monkeypatch.setattr(at, "_client_for", lambda config: claude)
        holder["claude"] = claude
        return claude

    return install


class _Answer(BaseModel):
    answer: str


# --- request shape -----------------------------------------------------------

def test_haiku_gets_no_sampling_parameters_and_effort_per_tier(fake):
    """Haiku 5.5 rejects temperature with a 400; effort is the lever instead."""
    claude = fake(_message(_text("OK")), _message(_text("OK")))
    root = LLMClient(_cfg(temperature=0.0))

    root.for_tier(WORKHORSE_TIER).complete([{"role": "user", "content": "hi"}])
    root.for_tier(REASONING_TIER).complete([{"role": "user", "content": "hi"}])

    work, reason = claude.requests
    for params in (work, reason):
        assert "temperature" not in params and "extra_body" not in params
        assert "thinking" not in params, "Haiku 5.5 thinks adaptively by default"
    assert work["output_config"]["effort"] == "low"
    assert reason["output_config"]["effort"] == "medium"


def test_the_instructions_are_cached_for_every_call_of_a_kind(fake):
    """Every classify batch, every describe batch, every user shares these."""
    claude = fake(_message(_text('{"answer": "x"}')))
    LLMClient(_cfg()).complete_json(system="S", developer="D", user="U", schema=_Answer)

    params = claude.requests[0]
    assert params["system"][0]["text"] == "S"
    assert params["system"][-1]["text"].startswith("[developer instructions]\nD")
    assert params["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in params, "a one-shot call has nothing to read the cache back"
    assert params["messages"] == [{"role": "user", "content": "U"}]
    assert params["max_tokens"] >= at.MIN_MAX_TOKENS, "thinking counts against max_tokens"


def test_the_tool_loop_caches_the_growing_conversation(fake):
    claude = fake(_message(_text('{"answer": "x"}')))
    tool = ToolSpec("echo", "echo", {"type": "object"}, lambda a: {})
    LLMClient(_cfg()).complete_agentic(system="s", developer="d", user="u", schema=_Answer, tools=[tool])
    assert claude.requests[0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize(
    "model,effort,thinking,sampling",
    [
        ("claude-haiku-4-5", False, False, True),  # predates effort and adaptive thinking
        ("claude-opus-4-8", True, True, False),  # thinks only when asked; no sampling
        ("claude-sonnet-4-6", True, True, False),  # temperature only with thinking off
        ("claude-sonnet-5-5", True, False, False),
        ("some-future-model", False, False, False),  # nothing it could reject
    ],
)
def test_each_model_gets_only_what_it_accepts(fake, model, effort, thinking, sampling):
    claude = fake(_message(_text("OK"), model=model))
    LLMClient(_cfg(model=model, temperature=0.0)).complete([{"role": "user", "content": "hi"}])

    params = claude.requests[0]
    assert ("effort" in (params.get("output_config") or {})) is effort
    assert (params.get("thinking") == {"type": "adaptive"}) is thinking
    assert ("temperature" in (params.get("extra_body") or {})) is sampling


def test_a_temperature_refusal_drops_the_temperature_not_the_thinking(fake):
    """A 4.6 model's 400 names both; losing thinking would be the wrong repair."""
    claude = fake(
        _status(anthropic.BadRequestError, 400,
                "`temperature` may only be set to 1 when thinking is enabled or in adaptive mode"),
        _message(_text("OK"), model="claude-haiku-4-5"),
    )
    LLMClient(_cfg(model="claude-haiku-4-5", temperature=0.0)).complete([{"role": "user", "content": "hi"}])
    assert "temperature" in claude.requests[0]["extra_body"]
    assert "extra_body" not in claude.requests[1]


def test_system_messages_become_claudes_system_field(fake):
    claude = fake(_message(_text("hello world")))
    out = LLMClient(_cfg()).complete(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    )
    assert out == "hello world"
    assert claude.requests[0]["system"][0]["text"] == "sys"
    assert claude.requests[0]["messages"] == [{"role": "user", "content": "hi"}]


# --- structured outputs --------------------------------------------------------

def test_fixed_shape_answers_are_held_to_a_schema(fake):
    claude = fake(_message(_text('{"document_type_guess": "x", "classifications": [], "sections": []}')))
    LLMClient(_cfg()).complete_json(system="s", developer="d", user="u", schema=LLMClassifyResponse)

    fmt = claude.requests[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    element = fmt["schema"]["$defs"]["LLMElementClassification"]
    assert element["additionalProperties"] is False
    assert "REPEATABLE_TABLE" in element["properties"]["classification"]["enum"]


def test_value_bearing_answers_keep_the_parser(fake):
    """A writer answer's values are free-form; no fixed schema can describe them."""
    assert response_schema(LLMWriteResponse) is None
    claude = fake(_message(_text('{"placements": []}')))
    LLMClient(_cfg()).complete_json(system="s", developer="d", user="u", schema=LLMWriteResponse)
    assert "format" not in (claude.requests[0].get("output_config") or {})


def test_a_schema_the_api_refuses_is_dropped_and_remembered(fake):
    good = _message(_text('{"document_type_guess": "x"}'))
    claude = fake(
        _status(anthropic.BadRequestError, 400, "output_config.format: schema is not supported"),
        good,
        good,
    )
    client = LLMClient(_cfg())
    client.complete_json(system="s", developer="d", user="u", schema=LLMClassifyResponse)
    client.complete_json(system="s", developer="d", user="u", schema=LLMClassifyResponse)

    first, retry, later = claude.requests
    assert "format" in first["output_config"]
    assert "format" not in retry.get("output_config", {})
    assert "format" not in later.get("output_config", {}), "the refusal was not remembered"


# --- the tool loop -------------------------------------------------------------

def test_the_tool_loop_returns_thinking_blocks_unchanged_and_all_results_together(fake):
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}
    calls = [
        {"type": "tool_use", "id": "t1", "name": "echo", "input": {"text": "a"}},
        {"type": "tool_use", "id": "t2", "name": "echo", "input": {"text": "b"}},
    ]
    claude = fake(
        _message([thinking, *calls], stop_reason="tool_use"),
        _message(_text('{"answer": "done"}')),
    )
    ran: list[str] = []
    tool = ToolSpec("echo", "echo text", {"type": "object"}, lambda a: ran.append(a["text"]) or {"ok": True})

    out = LLMClient(_cfg()).complete_agentic(
        system="s", developer="d", user="u", schema=_Answer, tools=[tool]
    )

    assert out.answer == "done" and ran == ["a", "b"]
    first, second = claude.requests
    assert first["tools"][0]["name"] == "echo"
    assert first["tools"][0]["eager_input_streaming"] is True
    assert first["tool_choice"] == {"type": "auto"}
    assistant, results = second["messages"][1], second["messages"][2]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0].type == "thinking"
    assert assistant["content"][0].signature == "sig-1", "thinking must go back unmodified"
    assert results["role"] == "user"
    assert [r["tool_use_id"] for r in results["content"]] == ["t1", "t2"]


def test_a_malformed_tool_input_is_an_error_result_not_a_crash(fake):
    """With eager input streaming the API stops validating tool inputs, and the
    SDK's tolerant parser can hand back something that is not an object."""
    call = _message([{"type": "tool_use", "id": "t1", "name": "echo", "input": {}}], stop_reason="tool_use")
    object.__setattr__(call.content[0], "input", "not-an-object")
    claude = fake(call, _message(_text('{"answer": "ok"}')))
    tool = ToolSpec("echo", "echo", {"type": "object"}, lambda a: {"ok": True})
    LLMClient(_cfg()).complete_agentic(system="s", developer="d", user="u", schema=_Answer, tools=[tool])

    result = claude.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True


# --- stop reasons and failures ---------------------------------------------------

def test_a_refusal_is_reported_with_its_category(fake):
    fake(_message([], stop_reason="refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}))
    with pytest.raises(LLMRefused) as exc:
        LLMClient(_cfg()).complete_json(system="s", developer="d", user="u", schema=_Answer)
    assert exc.value.category == "cyber"
    assert "cyber" in str(exc.value)


def test_a_truncated_answer_is_repaired_rather_than_discarded(fake):
    claude = fake(_message(_text('{"answer": "done", "notes": ["a", "b'), stop_reason="max_tokens"))
    out = LLMClient(_cfg()).complete_json(system="s", developer="d", user="u", schema=_Answer)
    assert out.answer == "done"
    assert len(claude.requests) == 1, "the complete part was usable; no retry needed"


def test_overload_becomes_unavailable_so_the_tier_fallback_can_act(fake):
    fake(_status(anthropic.OverloadedError, 529, "Overloaded"))
    with pytest.raises(LLMUnavailable):
        LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}])


def test_a_bad_key_says_so(fake):
    fake(_status(anthropic.AuthenticationError, 401, "invalid x-api-key"))
    with pytest.raises(LLMError, match="rejected the API key"):
        LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}])


def test_a_key_spanning_several_workspaces_gets_actionable_advice(fake):
    fake(_status(
        anthropic.BadRequestError, 400,
        "anthropic-workspace-id is required when authenticating with an identity-linked API key",
    ))
    with pytest.raises(LLMError, match="scoped to one workspace"):
        LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}])


def test_cancelling_mid_stream_stops_the_request(fake):
    cancel = threading.Event()
    events = [_Event("par")]
    claude = fake({"message": _message(_text("partial")), "events": events})

    def on_first(*_):
        cancel.set()

    events.append(_Event("tial"))
    transport = at.AnthropicTransport(_cfg())
    with pytest.raises(LLMCancelled):
        transport.turn(
            system=["s"], messages=[{"role": "user", "content": "hi"}],
            cancel_event=cancel, on_delta=on_first,
        )
    assert claude.streams[0].closed, "leaving the stream must close the connection"


def test_claude_is_cancellable_on_the_analysis_path():
    assert LLMClient(_cfg()).supports_streaming


def test_the_connection_check_spends_no_tokens(fake):
    claude = fake()
    transport = at.AnthropicTransport(_cfg())
    transport.check_model(HAIKU)
    with pytest.raises(LLMError, match="does not recognise"):
        transport.check_model("claude-nope")
    assert claude.requests == []


# --- cost ----------------------------------------------------------------------

def test_haiku_is_priced_by_the_size_of_each_prompt():
    short = pricing.cost_for_call(HAIKU, 50_000, 1_000)
    long = pricing.cost_for_call(HAIKU, 150_000, 1_000)
    assert short == pytest.approx((50_000 * 0.10 + 1_000 * 0.50) / 1e6)
    assert long == pytest.approx((150_000 * 0.50 + 1_000 * 2.50) / 1e6)


def test_cached_tokens_are_billed_at_cache_rates():
    cost = pricing.cost_for_call(HAIKU, 1_000, 0, cache_read=10_000, cache_write=2_000)
    expected = (1_000 * 0.10 + 10_000 * 0.10 * 0.1 + 2_000 * 0.10 * 1.25) / 1e6
    assert cost == pytest.approx(expected)


def test_opus_4_8_is_priced_correctly():
    assert pricing.price_for("claude-opus-4-8") == (5.00, 25.00)


def test_usage_records_cache_tokens_and_the_whole_prompt(fake):
    fake(_message(_text("OK"), usage={
        "input_tokens": 100, "output_tokens": 20,
        "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0,
    }))
    with track_usage() as usage:
        LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}])
    d = usage.as_dict()
    assert d["in"] == 1_000 and d["cache_read"] == 900 and d["out"] == 20
    assert d["cost_usd"] == pytest.approx(round((100 * 0.10 + 900 * 0.01 + 20 * 0.50) / 1e6, 6))
