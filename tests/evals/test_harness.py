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
