"""Runtime-mutable AI configuration.

Environment variables provide the defaults; a small JSON file under the data dir
(``app_settings.json``) lets the Settings UI override the AI provider/model/key
at runtime without a restart. The API key is stored server-side only and is
never returned to clients (see api/routes/settings.py).

For production, prefer setting the key via the environment; the file override is
a local-first convenience.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings

OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"
ANTHROPIC_DEFAULT_BASE = "https://api.anthropic.com"


@dataclass
class AIConfig:
    provider: str = "openai"  # "openai" | "anthropic"
    enabled: bool = False
    base_url: str = OPENAI_DEFAULT_BASE
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 120
    max_retries: int = 2
    max_output_tokens: int = 6000
    # Prepend /no_think to every system message for Qwen3 models running in LM
    # Studio so the chain-of-thought prefix is suppressed. Set via the Settings
    # UI or by adding "no_think": true to data/app_settings.json.
    no_think: bool = False

    @property
    def active(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url)


def _overrides_path() -> Path:
    return get_settings().data_dir / "app_settings.json"


def load_overrides() -> dict:
    path = _overrides_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_overrides(data: dict) -> None:
    settings = get_settings()
    settings.ensure_dirs()
    _overrides_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_ai_config() -> AIConfig:
    """Effective AI config = env defaults overlaid with the JSON overrides."""
    s = get_settings()
    cfg = AIConfig(
        provider=s.ai_provider,
        enabled=s.ai_enabled,
        base_url=s.ai_base_url,
        api_key=s.ai_api_key,
        model=s.ai_model,
        timeout_seconds=s.ai_timeout_seconds,
        max_retries=s.ai_max_retries,
        max_output_tokens=s.ai_max_output_tokens,
    )
    overrides = load_overrides().get("ai", {})
    for key, value in overrides.items():
        if hasattr(cfg, key) and value is not None:
            setattr(cfg, key, value)
    return cfg


def interactive_ai_config() -> AIConfig:
    """Effective AI config but with the shorter in-request timeout, so user-facing
    routing falls back to heuristics quickly instead of blocking the request."""
    cfg = get_ai_config()
    cfg.timeout_seconds = get_settings().ai_interactive_timeout_seconds
    return cfg


def update_ai_config(patch: dict) -> AIConfig:
    """Merge a patch into the persisted overrides. Blank api_key is ignored
    (so saving other settings doesn't wipe an existing key)."""
    data = load_overrides()
    ai = data.get("ai", {})
    for key in (
        "provider", "enabled", "base_url", "model",
        "timeout_seconds", "max_retries", "max_output_tokens", "no_think",
    ):
        if key in patch and patch[key] is not None:
            ai[key] = patch[key]
    if patch.get("api_key"):
        ai["api_key"] = patch["api_key"]
    data["ai"] = ai
    save_overrides(data)
    return get_ai_config()
