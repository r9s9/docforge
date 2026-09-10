"""A key you saved stays saved.

The failure this guards against was reported twice: someone opens Settings to
change model, saves, and their API key is gone. Two causes, both covered here —
one key column shared by every provider, and a masked field a browser password
manager can fill with an unrelated credential that the next save writes over.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docforge import ai_quota
from docforge.ai_keys import (
    forget_key,
    key_for,
    key_shape_error,
    normalize_endpoint,
    stored_keys,
    with_key,
)

OPENROUTER = "https://openrouter.ai/api/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"


def _row(*, enabled=True, api_key="", base_url=OPENROUTER, provider="openai"):
    return SimpleNamespace(
        enabled=enabled, api_key=api_key, base_url=base_url, provider=provider,
        model="", reasoning_model="", no_think=False, free_used=0,
    )


# --- the keyring itself ----------------------------------------------------

def test_a_key_saved_before_the_keyring_still_works():
    """Every existing row holds a bare string. Upgrading must not log them out."""
    assert key_for("sk-or-legacy", OPENROUTER) == "sk-or-legacy"
    # It answers for whatever endpoint the row points at — it is the only key
    # the row has ever held, so refusing it would lose a working setup.
    assert key_for("sk-or-legacy", GEMINI) == "sk-or-legacy"


def test_two_endpoints_hold_two_keys():
    raw = with_key("", OPENROUTER, "sk-or-one")
    raw = with_key(raw, GEMINI, "AIzaTwo")

    assert key_for(raw, OPENROUTER) == "sk-or-one"
    assert key_for(raw, GEMINI) == "AIzaTwo"
    assert sorted(stored_keys(raw)) == sorted([normalize_endpoint(GEMINI), normalize_endpoint(OPENROUTER)])


def test_switching_provider_and_back_returns_the_original_key():
    """The reported symptom, as a test."""
    raw = with_key("", GEMINI, "AIzaMine")
    raw = with_key(raw, OPENROUTER, "sk-or-mine")  # user moves to OpenRouter

    assert key_for(raw, GEMINI) == "AIzaMine", "the Gemini key was lost on the way out"
    assert key_for(raw, OPENROUTER) == "sk-or-mine"


def test_a_legacy_key_keeps_its_own_endpoint_when_the_row_moves():
    """Save a new key while repointing the row: the old one must not follow."""
    raw = with_key("AIzaLegacy", OPENROUTER, "sk-or-new", legacy_base=GEMINI)

    assert key_for(raw, GEMINI) == "AIzaLegacy"
    assert key_for(raw, OPENROUTER) == "sk-or-new"


def test_an_endpoint_means_one_key_however_it_was_typed():
    raw = with_key("", "https://OpenRouter.ai/api/v1/", "sk-or-one")
    assert key_for(raw, OPENROUTER) == "sk-or-one"
    assert len(stored_keys(raw)) == 1


def test_no_key_is_not_an_error():
    assert key_for("", OPENROUTER) == ""
    assert key_for(None, OPENROUTER) == ""
    assert stored_keys(None) == {}
    assert with_key("", OPENROUTER, "  ") == ""


def test_forgetting_one_key_leaves_the_others():
    raw = with_key(with_key("", OPENROUTER, "sk-or-one"), GEMINI, "AIzaTwo")
    raw = forget_key(raw, OPENROUTER)

    assert key_for(raw, OPENROUTER) == ""
    assert key_for(raw, GEMINI) == "AIzaTwo"


# --- refusing the autofilled credential ------------------------------------

@pytest.mark.parametrize(
    "base_url,key",
    [
        (OPENROUTER, "sk-or-v1-abc"),
        (GEMINI, "AIzaSyAbc"),
        ("https://api.anthropic.com", "sk-ant-abc"),
        ("https://api.openai.com/v1", "sk-abc"),
        ("http://localhost:1234/v1", "anything-a-local-server-wants"),
        ("https://some-new-gateway.example/v1", "whatever-shape-this-is"),
    ],
)
def test_a_plausible_key_is_accepted(base_url, key):
    assert key_shape_error(base_url, key) is None


@pytest.mark.parametrize("base_url", [OPENROUTER, GEMINI, "https://api.anthropic.com"])
def test_a_website_password_is_refused(base_url):
    """What a password manager fills in — and what used to overwrite the key."""
    problem = key_shape_error(base_url, "hunter2-my-github-password")
    assert problem and "browser" in problem


def test_a_blank_submission_is_not_a_shape_problem():
    """Blank means "keep what you have", which the route handles separately."""
    assert key_shape_error(OPENROUTER, "") is None


# --- one answer to "is a key configured?" ----------------------------------

def test_the_pipeline_sends_the_key_for_the_endpoint_it_is_calling(monkeypatch):
    raw = with_key(with_key("", OPENROUTER, "sk-or-one"), GEMINI, "AIzaTwo")
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(api_key=raw, base_url=GEMINI))

    plan = ai_quota.plan_ai_for_owner("u1")

    assert plan.mode == "own"
    assert plan.config.api_key == "AIzaTwo", "sent the key belonging to a different provider"


def test_a_key_for_another_endpoint_does_not_count_as_having_one(monkeypatch):
    """has_own_key must mean "for the endpoint we are about to call"."""
    raw = with_key("", GEMINI, "AIzaTwo")
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(api_key=raw, base_url=OPENROUTER))

    assert ai_quota._has_own(_row(api_key=raw, base_url=OPENROUTER)) is False
    assert ai_quota._has_own(_row(api_key=raw, base_url=GEMINI)) is True
