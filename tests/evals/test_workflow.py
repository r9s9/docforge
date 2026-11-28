"""The CI workflow (``.github/workflows/evals.yml``) runs the gate the design describes (§8)."""

from __future__ import annotations

import yaml

from evals.paths import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "evals.yml"


def _workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1 reads the bare key `on` as true
    return data


def test_it_runs_on_pull_requests_and_pushes_to_evals_and_by_hand():
    on = _workflow()["on"]
    assert on["pull_request"]["branches"] == ["evals"]
    assert on["push"]["branches"] == ["evals"]
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"suite", "max_usd"} and inputs["max_usd"]["required"] is True
    assert _workflow()["permissions"] == {"contents": "read"}


def test_the_gate_job_runs_the_checks_in_order_on_python_3_11():
    gate = _workflow()["jobs"]["gate"]
    assert gate["if"] == "github.event_name != 'workflow_dispatch'"
    steps = gate["steps"]
    python = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python"))
    assert python["with"]["python-version"] == "3.11"
    commands = [s["run"] for s in steps if "run" in s]
    order = ["pip install -e \"backend[dev]\"", "python -m evals corpus check", "ruff check",
             "python -m pytest tests/evals", "python -m evals run --suite all --config "
             "evals/configs/no-ai.yaml", "python -m evals gate", "python -m evals report --check"]
    positions = [next(i for i, c in enumerate(commands) if wanted in c) for wanted in order]
    assert positions == sorted(positions)


def test_the_ai_job_runs_only_by_hand_capped_and_never_puts_inputs_in_a_command():
    ai = _workflow()["jobs"]["ai"]
    assert ai["if"] == "github.event_name == 'workflow_dispatch'"
    assert ai["env"]["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    commands = [s["run"] for s in ai["steps"] if "run" in s]
    assert all("${{" not in command for command in commands)  # inputs arrive as variables
    runs = [c for c in commands if "python -m evals run" in c]
    assert runs and all('--max-usd "$MAX_USD"' in c and "evals/configs/haiku.yaml" in c
                        for c in runs)
    assert "ANTHROPIC_API_KEY" in commands[0] and "exit 1" in commands[0]  # no key: stop first
