"""The spending cap for AI runs (brief §6.3 and §9).

- **The cap.** The stricter of ``--max-usd`` (default $3, the brief's cap) and the config's own
  ``max_usd``. A config can make the cap lower but never higher.
- **The estimate.** Before a run: the mean cost of a judged case in the last run of the same
  config, times the judged cases not yet in the cache. Without such a run there is no estimate,
  and the first few judged cases act as a pilot (``projected``).
- **The stop.** During a run, live spend is checked after every case. The run stops once it
  reaches the cap, or once the pilot projects past it, and the result is marked ``stopped``.

Only live spend counts: replayed answers cost nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_MAX_USD = 3.0
PILOT_CASES = 3


def effective_cap(config: dict[str, Any], cli_cap: float | None) -> float:
    """The stricter of the command-line cap (or the default) and the config's ``max_usd``."""
    caps = [DEFAULT_MAX_USD if cli_cap is None else float(cli_cap)]
    if config.get("max_usd") is not None:
        caps.append(float(config["max_usd"]))
    return min(caps)


def latest_result(results_dir: Path, config_name: str, suite: str) -> dict[str, Any] | None:
    """The newest committed result of a config and suite, or None."""
    paths = sorted(Path(results_dir).glob(f"*_{config_name}_{suite}.json"))
    if not paths:
        return None
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def judged_case_ids(no_ai_result: dict[str, Any] | None) -> set[str] | None:
    """Cases the judge will see: those whose deterministic check reported differences.

    The deterministic check gives the same differences in every mode, so the no-AI result
    says exactly which cases will cost money. None when there is no no-AI result.
    """
    if no_ai_result is None:
        return None
    return {case["id"] for case in no_ai_result["cases"] if case.get("differences")}


def cost_per_judged_case(prior: dict[str, Any] | None) -> float | None:
    """Mean cost of a judged case (live + replayed, i.e. what it costs uncached) in a run."""
    if prior is None:
        return None
    costs = [
        case["spend_usd"]["live"] + case["spend_usd"]["replayed"]
        for case in prior["cases"]
        if (case.get("judge") or {}).get("status") == "ran" and case.get("spend_usd")
    ]
    return sum(costs) / len(costs) if costs else None


def cost_per_case(prior: dict[str, Any] | None, suite: str) -> float | None:
    """Mean cost of one model-calling case in an earlier run of a suite, grading included.

    Comply counts the cases the judge saw. Generate counts every case that called a model:
    all of them with AI on, and the graded ones with AI off. Analyze counts every analysis,
    since with AI on each one calls the model.
    """
    if prior is None:
        return None
    if suite == "comply":
        return cost_per_judged_case(prior)
    costs = []
    for case in prior["cases"]:
        spend = case.get("spend_usd") or {}
        grading = case.get("grader_spend_usd") or {}
        if case.get("error") or not (case.get("ai") or grading):
            continue
        costs.append(sum(spend.get(k, 0.0) + grading.get(k, 0.0) for k in ("live", "replayed")))
    return sum(costs) / len(costs) if costs else None


def estimate(judged: set[str] | None, cached: set[str], per_case: float | None) -> float | None:
    """Projected live spend: judged cases not yet cached, times the cost of one."""
    if judged is None or per_case is None:
        return None
    return len(judged - cached) * per_case


def projected(spent: float, judged_done: int, judged_total: int) -> float | None:
    """Live spend projected to the whole run from the judged cases done so far."""
    if judged_done < PILOT_CASES:
        return None
    return spent / judged_done * judged_total


def stop_reason(spent: float, cap: float, judged_done: int, judged_total: int,
                *, have_estimate: bool) -> str | None:
    """Why the run must stop now, or None to go on."""
    if spent >= cap:
        return "budget"
    if not have_estimate:
        projection = projected(spent, judged_done, judged_total)
        if projection is not None and projection > cap:
            return "budget_projection"
    return None
