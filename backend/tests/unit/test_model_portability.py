"""The AI layer must not assume it is talking to GPT or Gemini.

Two shapes of endpoint break the old assumptions. A *gateway* (OpenRouter)
serves many models from one base URL and answers 404 when no upstream can do
what was asked. A *reasoning model* returns its chain of thought in a field of
its own, and mirrors back the annotated pseudo-JSON our prompts show it.
"""

from __future__ import annotations

import httpx
import pytest

from docforge.ai import client as ai_client
from docforge.ai.client import (
    _JSON_MODE_UNSUPPORTED,
    _TOOLS_UNSUPPORTED,
    LLMClient,
    _extract_json,
    _message_text,
)
from docforge.ai.tools import ToolSpec
from docforge.ai.prompts import LLMUnderstanding
from docforge.settings_store import REASONING_TIER, WORKHORSE_TIER, AIConfig

GATEWAY = "https://openrouter.ai/api/v1"
ULTRA = "nvidia/nemotron-3-ultra-550b-a55b"
SUPER = "nvidia/nemotron-3-super-120b-a12b"


class _Resp:
    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text or ""
        self.headers = {}
        self.reason_phrase = ""

    def json(self):
        return self._data


def _cfg(**kw):
    base = dict(
        provider="openai", enabled=True, base_url=GATEWAY, api_key="sk-or-v1-k", model=ULTRA
    )
    base.update(kw)
    return AIConfig(**base)


@pytest.fixture(autouse=True)
def _clean_caches():
    """The capability caches are process-global; a leak between tests is a lie."""
    _JSON_MODE_UNSUPPORTED.clear()
    _TOOLS_UNSUPPORTED.clear()
    yield
    _JSON_MODE_UNSUPPORTED.clear()
    _TOOLS_UNSUPPORTED.clear()


def _ok(content="OK"):
    return _Resp(200, {"choices": [{"message": {"content": content}}]})


# --- capability caches are per model, not per endpoint ----------------------

def test_one_model_losing_json_mode_does_not_disable_it_for_the_next(monkeypatch):
    """A gateway serves every model from one base URL."""
    seen: list[tuple[str, bool]] = []

    def fake_post(self, url, **kw):
        body = kw.get("json", {})
        seen.append((body["model"], "response_format" in body))
        if body["model"] == SUPER and "response_format" in body:
            return _Resp(400, {"error": "response_format is not supported"})
        return _ok()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg(model=SUPER)).complete([{"role": "user", "content": "hi"}], json_mode=True)
    LLMClient(_cfg(model=ULTRA)).complete([{"role": "user", "content": "hi"}], json_mode=True)

    assert seen == [(SUPER, True), (SUPER, False), (ULTRA, True)], (
        "the second model was denied JSON mode because the first could not do it"
    )


def test_a_tool_rejection_is_remembered_per_model(monkeypatch):
    tool = ToolSpec(name="t", description="d", parameters={"type": "object"}, func=lambda **a: {})

    def fake_post(self, url, **kw):
        body = kw["json"]
        if body["model"] == SUPER and "tools" in body:
            return _Resp(400, {"error": "tools are not supported"}, text="tools are not supported")
        return _ok('{"summary": "fine"}')

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg(model=SUPER)).complete_agentic(
        system="s", developer="d", user="u", schema=LLMUnderstanding, tools=[tool]
    )

    assert (GATEWAY + "/", SUPER) in _TOOLS_UNSUPPORTED
    assert (GATEWAY + "/", ULTRA) not in _TOOLS_UNSUPPORTED


# --- a gateway says "cannot" with 404, not 400 ------------------------------

def test_a_404_on_tools_degrades_instead_of_failing_the_action(monkeypatch):
    """OpenRouter answers 404 when no upstream implements tool calling.

    Treated as fatal, that turned "this model has no tools" into "AI failed",
    and the caller dropped the whole action to the offline engine.
    """
    tool = ToolSpec(name="t", description="d", parameters={"type": "object"}, func=lambda **a: {})

    def fake_post(self, url, **kw):
        if "tools" in kw.get("json", {}):
            return _Resp(404, {"error": "No endpoints found that support tool use"})
        return _ok('{"summary": "answered anyway"}')

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = LLMClient(_cfg()).complete_agentic(
        system="s", developer="d", user="u", schema=LLMUnderstanding, tools=[tool]
    )

    assert out.summary == "answered anyway"


def test_a_404_on_json_mode_retries_as_prose(monkeypatch):
    def fake_post(self, url, **kw):
        if "response_format" in kw.get("json", {}):
            return _Resp(404, {"error": "No endpoints found that support JSON mode"})
        return _ok("plain text")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    assert LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}], json_mode=True) == "plain text"


# --- a gateway must be told the capability is required ----------------------

def test_json_mode_on_a_gateway_requires_a_capable_upstream(monkeypatch):
    sent = {}

    def fake_post(self, url, **kw):
        sent.update(kw["json"])
        return _ok()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}], json_mode=True)

    assert sent["provider"] == {"require_parameters": True}


def test_a_single_vendor_endpoint_is_not_told_about_provider_routing(monkeypatch):
    sent = {}

    def fake_post(self, url, **kw):
        sent.update(kw["json"])
        return _ok()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg(base_url="https://api.openai.com/v1", model="gpt-4o-mini")).complete(
        [{"role": "user", "content": "hi"}], json_mode=True
    )

    assert "provider" not in sent


def test_the_gateway_gets_attribution_headers(monkeypatch):
    seen = {}

    def fake_post(self, url, **kw):
        seen.update(kw["headers"])
        return _ok()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}])

    assert seen["X-Title"] == "DocForge"
    assert seen["Authorization"] == "Bearer sk-or-v1-k"


# --- reasoning --------------------------------------------------------------

def test_the_workhorse_tier_is_told_not_to_think():
    cfg = _cfg(model=SUPER, reasoning_model=ULTRA, reasoning_effort="high")
    root = LLMClient(cfg)

    assert root.for_tier(WORKHORSE_TIER).config.tier_reasoning_effort == "none"
    assert root.for_tier(REASONING_TIER).config.tier_reasoning_effort == "high"
    assert root.for_tier(REASONING_TIER).config.model == ULTRA


def test_reasoning_is_left_to_the_provider_unless_configured():
    """The safe default: some models cannot stop reasoning at all."""
    root = LLMClient(_cfg())

    assert root.for_tier(WORKHORSE_TIER).config.tier_reasoning_effort == ""
    assert root.for_tier(REASONING_TIER).config.tier_reasoning_effort == ""


def test_the_effort_reaches_the_request(monkeypatch):
    sent = {}

    def fake_post(self, url, **kw):
        sent.update(kw["json"])
        return _ok()

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    LLMClient(_cfg(reasoning_effort="medium")).for_tier(WORKHORSE_TIER).complete(
        [{"role": "user", "content": "hi"}]
    )

    assert sent["reasoning"] == {"effort": "none"}


def test_an_answer_hiding_in_the_reasoning_field_is_still_an_answer():
    assert _message_text({"content": "", "reasoning": '{"a": 1}'}) == '{"a": 1}'
    assert _message_text({"content": None, "reasoning_content": "fallback"}) == "fallback"


def test_the_reasoning_field_never_overrides_a_real_answer():
    """Feeding the model's deliberation to the parser would be worse than useless."""
    assert _message_text({"content": '{"real": true}', "reasoning": "hmm, maybe {}"}) == '{"real": true}'


def test_an_empty_content_reasoning_response_is_read(monkeypatch):
    def fake_post(self, url, **kw):
        return _Resp(200, {"choices": [{"message": {"content": "", "reasoning": "the answer"}}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    assert LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}]) == "the answer"


# --- what models actually emit ---------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1,}', {"a": 1}),
        ('{"a": 1, // why\n "b": 2}', {"a": 1, "b": 2}),
        ('{"a": 1 /* why */, "b": 2}', {"a": 1, "b": 2}),
        ("Let me think about this. {\"a\": [1,2", {"a": [1]}),
        ('<think>hmm{"a": 1}', {"a": 1}),
        ('<thinking>plan</thinking>{"a": 1}', {"a": 1}),
    ],
)
def test_the_ways_open_models_get_json_wrong(raw, expected):
    assert _extract_json(raw) == expected


def test_a_url_is_not_a_comment():
    assert _extract_json('{"u": "https://x.dev//p"}') == {"u": "https://x.dev//p"}


def test_our_own_prompts_stop_teaching_the_comment_style():
    """The schemas are shown with // notes; models mirror that back as output."""
    from pathlib import Path

    from docforge.ai import prompts

    text = Path(prompts.__file__).read_text(encoding="utf-8")
    assert text.count("no comments") == text.count("Output valid JSON only")


# --- transient conditions ---------------------------------------------------

def test_a_proxy_timeout_is_retried(monkeypatch):
    """Cloudflare answers 524 while a slow reasoning model is still thinking."""
    calls = {"n": 0}

    def fake_post(self, url, **kw):
        calls["n"] += 1
        return _ok() if calls["n"] > 1 else _Resp(524, {"error": "timeout"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)

    assert LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}]) == "OK"
    assert calls["n"] == 2


# --- the shipped default ----------------------------------------------------

def test_the_recommended_models_have_a_price():
    """An unpriced model shows token counts with no cost estimate in the UI."""
    from docforge.ai.pricing import price_for
    from docforge.settings_store import NEMOTRON_REASONING_MODEL, NEMOTRON_WORKHORSE_MODEL

    workhorse = price_for(NEMOTRON_WORKHORSE_MODEL)
    reasoning = price_for(NEMOTRON_REASONING_MODEL)

    assert workhorse and reasoning
    assert workhorse[0] < reasoning[0], "the workhorse must be the cheaper of the pair"


def test_openrouter_is_recognised_as_a_gateway():
    from docforge.settings_store import OPENROUTER_DEFAULT_BASE

    assert LLMClient(_cfg(base_url=OPENROUTER_DEFAULT_BASE))._is_gateway()
    assert not LLMClient(_cfg(base_url="https://api.openai.com/v1"))._is_gateway()
