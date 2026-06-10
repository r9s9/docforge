"""Unit tests for per-user AI plan resolution and the free-tier quota."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docforge import ai_quota
from docforge.config import get_settings


def _row(*, enabled=False, api_key="", free_used=0, provider="openai", base_url="", model=""):
    return SimpleNamespace(
        enabled=enabled,
        api_key=api_key,
        free_used=free_used,
        provider=provider,
        base_url=base_url,
        model=model,
        no_think=False,
    )


@pytest.fixture
def free_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "free_ai_enabled", True)
    monkeypatch.setattr(s, "free_ai_api_key", "sk-ant-test")
    monkeypatch.setattr(s, "free_ai_provider", "anthropic")
    monkeypatch.setattr(s, "free_ai_base_url", "https://api.anthropic.com")
    monkeypatch.setattr(s, "free_ai_model", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(s, "free_ai_limit", 10)
    return s


def test_own_key_wins(monkeypatch, free_settings):
    monkeypatch.setattr(
        ai_quota, "_row", lambda oid: _row(enabled=True, api_key="sk-mine", base_url="https://x/v1")
    )
    plan = ai_quota.plan_ai_for_owner("u1")
    assert plan.mode == "own"
    assert plan.config.api_key == "sk-mine"
    assert plan.config.active is True
    assert plan.counts_against_free is False


def test_free_tier_when_no_own_key(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(free_used=3))
    plan = ai_quota.plan_ai_for_owner("u1")
    assert plan.mode == "free"
    assert plan.config.model == "claude-haiku-4-5-20251001"
    assert plan.config.api_key == "sk-ant-test"  # the shared key, used server-side only
    assert plan.counts_against_free is True


def test_free_tier_exhausted_falls_back_to_offline(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(free_used=10))
    plan = ai_quota.plan_ai_for_owner("u1")
    assert plan.mode == "none"
    assert plan.config.active is False  # -> heuristic engine


def test_previews_never_spend_free_credit(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(free_used=0))
    plan = ai_quota.plan_ai_for_owner("u1", allow_free=False)
    assert plan.mode == "none"
    assert plan.counts_against_free is False


def test_brand_new_user_gets_free_tier(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: None)  # no row yet
    plan = ai_quota.plan_ai_for_owner("new-user")
    assert plan.mode == "free"


def test_falls_back_to_global_when_free_disabled(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "free_ai_enabled", False)
    monkeypatch.setattr(ai_quota, "_row", lambda oid: None)
    # No global key configured in the hermetic test env -> "none".
    plan = ai_quota.plan_ai_for_owner("u1")
    assert plan.mode in ("global", "none")
    assert plan.mode == "none"  # global key is empty in tests


def test_usage_snapshot_shape(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(free_used=4))
    snap = ai_quota.usage_snapshot("u1")
    assert snap == {
        "free_enabled": True,
        "free_limit": 10,
        "free_used": 4,
        "free_remaining": 6,
        "has_own_key": False,
    }


def test_use_ai_plan_publishes_config(monkeypatch, free_settings):
    monkeypatch.setattr(ai_quota, "_row", lambda oid: _row(free_used=0))
    from docforge.settings_store import get_ai_config

    assert ai_quota.planned_ai_config() is None
    plan = ai_quota.plan_ai_for_owner("u1")
    with ai_quota.use_ai_plan(plan):
        # get_ai_config must transparently resolve to the planned (free) config.
        assert get_ai_config().model == "claude-haiku-4-5-20251001"
        assert ai_quota.planned_ai_config() is plan.config
    assert ai_quota.planned_ai_config() is None  # scope cleaned up
