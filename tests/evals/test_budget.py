"""Budget rules on hand-worked numbers."""

from __future__ import annotations

import json

import pytest

from evals.budget import (
    DEFAULT_MAX_USD,
    cost_per_judged_case,
    effective_cap,
    estimate,
    judged_case_ids,
    latest_result,
    projected,
    stop_reason,
)


def test_the_stricter_cap_wins():
    haiku = {"max_usd": 1.0}
    assert effective_cap(haiku, None) == 1.0
    assert effective_cap(haiku, 0.5) == 0.5
    assert effective_cap(haiku, 5.0) == 1.0  # a command can't raise the config's cap
    assert effective_cap({}, None) == DEFAULT_MAX_USD
    assert effective_cap({}, 2.0) == 2.0


def test_judged_cases_are_the_ones_with_differences():
    no_ai = {"cases": [{"id": "a", "differences": [{"kind": "x"}]}, {"id": "b", "differences": []}]}
    assert judged_case_ids(no_ai) == {"a"}
    assert judged_case_ids(None) is None


def test_cost_per_judged_case_counts_live_and_replayed():
    prior = {"cases": [
        {"judge": {"status": "ran"}, "spend_usd": {"live": 0.002, "replayed": 0.0}},
        {"judge": {"status": "ran"}, "spend_usd": {"live": 0.0, "replayed": 0.004}},
        {"judge": {"status": "not_needed"}, "spend_usd": {"live": 0.0, "replayed": 0.0}},
    ]}
    assert cost_per_judged_case(prior) == pytest.approx(0.003)
    assert cost_per_judged_case(None) is None


def test_estimate_skips_cached_cases():
    assert estimate({"a", "b", "c"}, {"b"}, 0.01) == pytest.approx(0.02)
    assert estimate(None, set(), 0.01) is None
    assert estimate({"a"}, set(), None) is None


def test_projection_waits_for_the_pilot():
    assert projected(0.01, 2, 100) is None
    assert projected(0.03, 3, 100) == pytest.approx(1.0)


def test_stop_reasons():
    assert stop_reason(1.0, 1.0, 10, 100, have_estimate=True) == "budget"
    assert stop_reason(0.5, 1.0, 10, 100, have_estimate=True) is None
    # Without an estimate, the pilot projects 0.05 / 3 * 100 = 1.67 > 1.00.
    assert stop_reason(0.05, 1.0, 3, 100, have_estimate=False) == "budget_projection"
    assert stop_reason(0.02, 1.0, 3, 100, have_estimate=False) is None


def test_latest_result_picks_the_newest_file(tmp_path):
    for date in ("2026-11-25", "2026-11-26"):
        (tmp_path / f"{date}_haiku_comply.json").write_text(json.dumps({"date": date}))
    (tmp_path / "2026-11-27_local_comply.json").write_text(json.dumps({"date": "other"}))
    assert latest_result(tmp_path, "haiku", "comply") == {"date": "2026-11-26"}
    assert latest_result(tmp_path, "sonnet", "comply") is None


def test_the_plan_counts_the_repeat_calls_in_the_estimate(tmp_path, monkeypatch):
    import argparse

    from evals import cli, paths

    def case(case_id, differences, spend=None, status=None):
        return {"id": case_id, "differences": [{}] * differences, "spend_usd": spend,
                "judge": {"status": status} if status else None}

    no_ai = {"cases": [case("a", 1), case("b", 2), case("c", 1), case("clean", 0)]}
    paid = {"live": 0.01, "replayed": 0.0}
    haiku = {"cases": [case("a", 1, paid, "ran"), case("b", 2, paid, "ran")]}
    (tmp_path / "2026-11-26_no-ai_comply.json").write_text(json.dumps(no_ai), encoding="utf-8")
    (tmp_path / "2026-11-26_haiku_comply.json").write_text(json.dumps(haiku), encoding="utf-8")
    monkeypatch.setattr(paths, "RESULTS_DIR", tmp_path)

    class Cache:
        def is_complete(self, case_id):
            return case_id == "a"

    selected = [{"id": i, "pair": "nda_en"} for i in ("a", "b", "c", "clean")]
    args = argparse.Namespace(no_cache=False, max_usd=None, repeat=3, sample=2)
    plan = cli._plan_budget({"name": "haiku", "max_usd": 1.0}, args, selected, Cache())
    # b and c are judged and not cached; the sample of 2 is judged twice more: 2 + 4 calls.
    assert plan["judged_expected"] == 3 and plan["cached"] == 1 and plan["repeat_calls"] == 4
    assert plan["estimate_usd"] == pytest.approx(0.06)
    assert plan["cap_usd"] == 1.0
    text = cli._dry_run_text({"name": "haiku"}, {"enabled": True, "model": "m", "host": "h"},
                             selected, plan)
    assert "repeat judge calls        4 (stability)" in text

    args.repeat = 1
    assert cli._plan_budget({"name": "haiku"}, args, selected, Cache())["repeat_calls"] == 0


def test_a_local_model_shows_no_price_even_with_an_earlier_result():
    from evals import cli

    plan = {"judged_expected": 82, "repeat_calls": 20, "cached": 0, "cap_usd": 3.0,
            "cost_per_judged_case": 0.0, "estimate_usd": 0.0}
    ai = {"enabled": True, "model": "qwen", "host": "127.0.0.1:1234"}
    text = cli._dry_run_text({"name": "local"}, ai, [{"id": "a", "pair": "nda_en"}], plan)
    assert "estimated cost            $0 (a local model has no price)" in text
    assert "$0.0000" not in text
