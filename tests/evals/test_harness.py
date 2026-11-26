"""The sandbox holds even when the working directory has a hostile ``.env``.

Each test runs in a subprocess, because DocForge reads its settings once per process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

HOSTILE_ENV = """\
DOCFORGE_STORAGE_BACKEND=supabase
DOCFORGE_SUPABASE_URL=https://storage.example.invalid
DOCFORGE_SUPABASE_SERVICE_ROLE_KEY=not-a-real-key
DOCFORGE_DATABASE_URL=postgresql://user:pass@db.example.invalid:5432/production
DOCFORGE_DATA_DIR=/should/never/be/used
DOCFORGE_FREE_AI_ENABLED=true
DOCFORGE_FREE_AI_API_KEY=sk-ant-not-a-real-key
DOCFORGE_AI_ENABLED=true
DOCFORGE_AI_API_KEY=sk-ant-not-a-real-key
DOCFORGE_MAX_UPLOAD_MB=7
"""

PROBE = """
import json
from evals.harness import apply_config, prepare
sandbox = prepare()
apply_config({"name": "no-ai", "ai": {"enabled": False}})
from docforge.ai_quota import plan_ai_for_owner
from docforge.config import get_settings
s = get_settings()
print(json.dumps({
    "root": str(sandbox.root),
    "data_dir": str(s.data_dir),
    "database_url": s.database_url,
    "storage_backend": s.storage_backend,
    "free_ai_enabled": s.free_ai_enabled,
    "ai_active": s.ai_active,
    "plan_active": plan_ai_for_owner(None).config.active,
    "max_upload_mb": s.max_upload_mb,
}))
sandbox.close()
"""


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DOCFORGE_")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


def test_sandbox_overrides_a_hostile_env_file(tmp_path):
    (tmp_path / ".env").write_text(HOSTILE_ENV)
    result = _run(PROBE, tmp_path)
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])
    assert seen["max_upload_mb"] == 7, "the .env file was not read at all; the test proves nothing"
    assert seen["storage_backend"] == "local"
    assert seen["database_url"].startswith("sqlite:///" + seen["root"])
    assert seen["data_dir"].startswith(seen["root"])
    assert seen["free_ai_enabled"] is False
    assert seen["ai_active"] is False
    assert seen["plan_active"] is False


def test_sandbox_refuses_once_settings_were_loaded(tmp_path):
    code = (
        "import docforge.config\n"
        "from evals.harness import SandboxError, prepare\n"
        "try:\n"
        "    prepare()\n"
        "except SandboxError:\n"
        "    print('refused')\n"
    )
    result = _run(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "refused"


def test_no_ai_config_loads():
    from evals.harness import load_config
    from evals.paths import CONFIGS_DIR

    config = load_config(CONFIGS_DIR / "no-ai.yaml")
    assert config["name"] == "no-ai" and config["ai"]["enabled"] is False


FAKE_KEY = "sk-ant-test-not-a-real-key-0451"

AI_PROBE = """
import json, os, sys
from evals.harness import ConfigError, apply_config, load_config, prepare
from evals.paths import CONFIGS_DIR
sandbox = prepare()
try:
    description = apply_config(load_config(CONFIGS_DIR / sys.argv[1]), model=sys.argv[2] or None)
except ConfigError as exc:
    print(json.dumps({"error": str(exc)}))
    raise SystemExit(0)
from docforge.ai_quota import plan_ai_for_owner
from docforge.config import get_settings
from docforge.settings_store import global_ai_config
s = get_settings()
print(json.dumps({
    "description": description,
    "ai_active": s.ai_active,
    "provider": s.ai_provider,
    "base_url": s.ai_base_url,
    "model": s.ai_model,
    "key_is_the_env_value": s.ai_api_key == os.environ.get("ANTHROPIC_API_KEY"),
    "plan_active": plan_ai_for_owner(None).config.active,
    "no_think": global_ai_config().no_think,
    "overrides_file": (s.data_dir / "app_settings.json").exists(),
}))
sandbox.close()
"""


def _probe_config(tmp_path, config: str, model: str = "", key: str | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    if key is not None:
        env["ANTHROPIC_API_KEY"] = key
    env = {k: v for k, v in env.items() if not k.startswith("DOCFORGE_")}
    env.update(PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", AI_PROBE, config, model], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert FAKE_KEY not in result.stdout + result.stderr, "the key was printed"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_haiku_config_switches_ai_on_with_the_key_from_the_environment(tmp_path):
    seen = _probe_config(tmp_path, "haiku.yaml", key=FAKE_KEY)
    assert seen["ai_active"] is True and seen["plan_active"] is True
    assert (seen["provider"], seen["model"]) == ("anthropic", "claude-haiku-5-5")
    assert seen["key_is_the_env_value"] is True
    assert seen["description"]["host"] == "api.anthropic.com"
    assert seen["description"]["effort"] == {"workhorse": "low", "reasoning": "medium"}
    # DocForge sends no temperature to Haiku 5.5, so the result must not claim temperature 0.
    assert seen["description"]["temperature_sent"] is False
    assert seen["no_think"] is False and seen["overrides_file"] is False


def test_haiku_config_without_a_key_stops_with_a_clear_message(tmp_path):
    seen = _probe_config(tmp_path, "haiku.yaml", key=None)
    assert "ANTHROPIC_API_KEY" in seen["error"] and "never printed or saved" in seen["error"]


def test_local_config_points_at_lm_studio_with_thinking_off(tmp_path):
    seen = _probe_config(tmp_path, "local.yaml", model="qwen-test")
    assert (seen["provider"], seen["base_url"], seen["model"]) == (
        "openai", "http://127.0.0.1:1234/v1", "qwen-test"
    )
    assert seen["ai_active"] is True
    assert seen["no_think"] is True and seen["overrides_file"] is True
    assert seen["description"]["no_think"] is True
    assert seen["description"]["temperature_sent"] is True


def _server(routes: dict):
    import httpx

    def handler(request):
        if request.url.path in routes:
            return httpx.Response(200, json=routes[request.url.path])
        return httpx.Response(404, json={"error": "not found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_detect_model_takes_the_one_loaded_chat_model_from_lm_studio():
    from evals.harness import detect_model

    client = _server({"/api/v0/models": {"data": [
        {"id": "qwen3.6-27b", "type": "llm", "state": "loaded", "quantization": "Q4_K_M",
         "max_context_length": 32768},
        {"id": "text-embedding-nomic", "type": "embeddings", "state": "loaded"},
        {"id": "another-llm", "type": "llm", "state": "not-loaded"},
    ]}})
    model = detect_model("http://127.0.0.1:1234/v1", client=client)
    assert model == {"id": "qwen3.6-27b", "quantization": "Q4_K_M", "max_context_length": 32768}


def test_detect_model_falls_back_to_the_openai_model_list():
    from evals.harness import detect_model

    client = _server({"/v1/models": {"data": [{"id": "qwen-x"}, {"id": "text-embedding-y"}]}})
    assert detect_model("http://127.0.0.1:1234/v1", client=client) == {"id": "qwen-x"}


def test_detect_model_refuses_to_guess_between_two_models():
    import pytest

    from evals.harness import ConfigError, detect_model

    client = _server({"/v1/models": {"data": [{"id": "model-a"}, {"id": "model-b"}]}})
    with pytest.raises(ConfigError, match="model-a, model-b"):
        detect_model("http://127.0.0.1:1234/v1", client=client)
