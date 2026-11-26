"""The sandbox every eval run happens in: DocForge pointed at a throwaway database and data dir.

``prepare()`` must run before anything imports ``docforge.config``. DocForge reads its settings
once (from the environment and a ``.env`` file in the working directory) and builds its database
engine when ``docforge.db.session`` is imported. Setting the environment first, and pinning
every setting that could reach outside the sandbox, means a developer's ``.env`` can't leak into
a run: no Supabase storage, no production database, no free-tier key. In pydantic-settings,
environment variables win over ``.env``.

The AI settings of a run come from its YAML config and are set on DocForge's settings object
in memory (``apply_config``). A key is read from the environment variable the config names, and
is never printed, logged or written anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Settings that could send data or spend money outside the sandbox. AI starts off; a config
# switches it on in memory (apply_config).
PINNED_ENV = {
    "DOCFORGE_STORAGE_BACKEND": "local",
    "DOCFORGE_FREE_AI_ENABLED": "false",
    "DOCFORGE_FREE_AI_API_KEY": "",
    "DOCFORGE_AI_ENABLED": "false",
    "DOCFORGE_AI_API_KEY": "",
    "DOCFORGE_AUTH_REQUIRED": "false",
    "DOCFORGE_SERVERLESS": "false",
    "DOCFORGE_LOG_LEVEL": "WARNING",
}

# Config keys under ``ai:`` and the DocForge setting each one sets.
_AI_SETTINGS = {
    "reasoning_model": "ai_reasoning_model",
    "effort_workhorse": "ai_effort_workhorse",
    "effort_reasoning": "ai_effort_reasoning",
    "temperature": "ai_temperature",
    "timeout_seconds": "ai_timeout_seconds",
    "max_output_tokens": "ai_max_output_tokens",
}


class SandboxError(RuntimeError):
    """The sandbox can't be set up safely."""


class ConfigError(ValueError):
    """A run config is missing something, or the model it names can't be found."""


@dataclass
class Sandbox:
    """A temp directory holding DocForge's data dir and SQLite database for one run."""

    root: Path
    data_dir: Path
    database_url: str
    keep: bool = False

    def close(self) -> None:
        """Remove the sandbox unless it was asked to be kept.

        DocForge's engine is disposed first: on Windows an open SQLite file can't be deleted.
        """
        try:
            from docforge.db.session import engine

            engine.dispose()
        except Exception:  # never fail a finished run over cleanup
            pass
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)


def prepare(root: Path | None = None, *, keep: bool = False) -> Sandbox:
    """Point DocForge at a fresh sandbox and create its tables."""
    if "docforge.config" in sys.modules:
        raise SandboxError(
            "docforge.config was imported before the sandbox was prepared; its settings may "
            "already come from somewhere else"
        )
    root = Path(root) if root else Path(tempfile.mkdtemp(prefix="docforge-evals-"))
    root.mkdir(parents=True, exist_ok=True)
    data_dir = root / "data"
    database_url = f"sqlite:///{root / 'evals.db'}"
    os.environ.update(
        {"DOCFORGE_DATA_DIR": str(data_dir), "DOCFORGE_DATABASE_URL": database_url, **PINNED_ENV}
    )

    from docforge.config import get_settings

    settings = get_settings()
    if (
        Path(settings.data_dir).resolve() != data_dir.resolve()
        or settings.database_url != database_url
        or settings.storage_backend != "local"
        or settings.free_ai_enabled
        or settings.ai_active
    ):
        raise SandboxError("DocForge's settings don't point at the sandbox")

    from docforge.db.session import init_db

    init_db()
    logging.getLogger("docforge").setLevel(logging.WARNING)
    return Sandbox(root=root, data_dir=data_dir, database_url=database_url, keep=keep)


def load_config(path: Path) -> dict[str, Any]:
    """Read a run config (``evals/configs/*.yaml``)."""
    import yaml

    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or "name" not in config or "ai" not in config:
        raise ConfigError(f"{path}: a config needs `name` and an `ai` section")
    return config


def ai_enabled(config: dict[str, Any]) -> bool:
    """Whether a config switches DocForge's AI on."""
    return bool((config.get("ai") or {}).get("enabled"))


def _api_key(config: dict[str, Any]) -> str:
    ai = config["ai"]
    if ai.get("api_key_env"):
        name = ai["api_key_env"]
        value = os.environ.get(name, "").strip()
        if not value:
            raise ConfigError(
                f"{config['name']}: set the {name} environment variable first. The key is read "
                "from there for this run only and is never printed or saved."
            )
        return value
    if ai.get("api_key_placeholder"):
        return str(ai["api_key_placeholder"])  # a local server ignores it; not a secret
    raise ConfigError(f"{config['name']}: the ai section needs api_key_env or api_key_placeholder")


def detect_model(base_url: str, client=None) -> dict[str, Any]:
    """The model an OpenAI-compatible local server has loaded (LM Studio first).

    LM Studio's own ``/api/v0/models`` says which models are loaded; the standard ``/v1/models``
    is the fallback for other servers. Exactly one chat model must be loaded, otherwise the run
    stops and lists what it found, so the choice is never a guess.
    """
    import httpx

    http = client or httpx.Client(timeout=10.0, trust_env=False)
    root = base_url.rstrip("/").removesuffix("/v1")
    found: list[dict[str, Any]] = []
    try:
        response = http.get(f"{root}/api/v0/models")
        if response.status_code == 200:
            found = [
                m for m in response.json().get("data", [])
                if m.get("state") == "loaded" and m.get("type", "llm") in ("llm", "vlm")
            ]
    except (httpx.HTTPError, ValueError):
        found = []
    if not found:
        try:
            response = http.get(f"{base_url.rstrip('/')}/models")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ConfigError(
                f"Can't reach the model server at {base_url} ({exc}). Is LM Studio's server "
                "running with a model loaded?"
            ) from exc
        found = [
            m for m in response.json().get("data", []) if "embed" not in str(m.get("id")).lower()
        ]
    if len(found) != 1:
        names = ", ".join(str(m.get("id")) for m in found) or "none"
        raise ConfigError(
            f"Expected exactly one loaded chat model at {base_url}, found: {names}. Load one, or "
            "pass `--model <id>`."
        )
    model = found[0]
    keys = ("id", "arch", "quantization", "max_context_length", "loaded_context_length")
    return {key: model[key] for key in keys if model.get(key) is not None}


def _sends_temperature(provider: str, model: str) -> bool | None:
    """Whether DocForge puts the temperature setting into this model's requests (None: unknown).

    The OpenAI-compatible path sends it in every request. On the Anthropic path DocForge sends
    it only to models that accept sampling parameters; Haiku 5.5 doesn't, so it runs at the
    API's default sampling whatever the config says.
    """
    if provider != "anthropic":
        return True
    try:
        from docforge.ai.anthropic_transport import profile_for
    except ImportError:
        return None
    return bool(profile_for(model).sampling)


def apply_config(config: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
    """Set a config's AI settings on DocForge; return a description of them without secrets."""
    from docforge.config import get_settings

    settings = get_settings()
    ai = config.get("ai") or {}
    if not ai.get("enabled"):
        settings.ai_enabled = False
        settings.ai_api_key = ""
        return {"enabled": False}

    for key in ("provider", "base_url", "model"):
        if not ai.get(key):
            raise ConfigError(f"{config['name']}: the ai section needs `{key}`")
    served: dict[str, Any] = {}
    model_id = model or ai["model"]
    if model_id == "auto":
        served = detect_model(ai["base_url"])
        model_id = served["id"]

    settings.ai_enabled = True
    settings.ai_provider = ai["provider"]
    settings.ai_base_url = ai["base_url"]
    settings.ai_api_key = _api_key(config)
    settings.ai_model = model_id
    for key, setting in _AI_SETTINGS.items():
        if key in ai and ai[key] is not None:
            setattr(settings, setting, ai[key])
    pipeline = config.get("pipeline") or {}
    if "writer_enabled" in pipeline:
        settings.ai_writer_enabled = bool(pipeline["writer_enabled"])
    if "verify_enabled" in pipeline:
        settings.ai_verify_enabled = bool(pipeline["verify_enabled"])

    if ai.get("no_think"):
        # DocForge reads no_think only from app_settings.json in its data dir: the sandbox's.
        overrides = Path(settings.data_dir) / "app_settings.json"
        overrides.parent.mkdir(parents=True, exist_ok=True)
        overrides.write_text(json.dumps({"ai": {"no_think": True}}), encoding="utf-8")

    return {
        "enabled": True,
        "provider": settings.ai_provider,
        "host": urlparse(settings.ai_base_url).netloc,
        "model": settings.ai_model,
        "reasoning_model": settings.ai_reasoning_model or settings.ai_model,
        "effort": {"workhorse": settings.ai_effort_workhorse,
                   "reasoning": settings.ai_effort_reasoning},
        "temperature": settings.ai_temperature,
        "temperature_sent": _sends_temperature(settings.ai_provider, settings.ai_model),
        "no_think": bool(ai.get("no_think")),
        **({"served": served} if served else {}),
    }
