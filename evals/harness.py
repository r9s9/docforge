"""The sandbox every eval run happens in: DocForge pointed at a throwaway database and data dir.

``prepare()`` must run before anything imports ``docforge.config``. DocForge reads its settings
once (from the environment and a ``.env`` file in the working directory) and builds its database
engine when ``docforge.db.session`` is imported. Setting the environment first, and pinning
every setting that could reach outside the sandbox, means a developer's ``.env`` can't leak into
a run: no Supabase storage, no production database, no free-tier key. In pydantic-settings,
environment variables win over ``.env``.

The AI settings of a run come from its YAML config and are set on DocForge's settings object
in memory. A key is read from the environment variable the config names, and is never printed
or written anywhere.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


class SandboxError(RuntimeError):
    """The sandbox can't be set up safely."""


class ConfigError(ValueError):
    """A run config is missing something or asks for something not supported yet."""


@dataclass
class Sandbox:
    """A temp directory holding DocForge's data dir and SQLite database for one run."""

    root: Path
    data_dir: Path
    database_url: str
    keep: bool = False

    def close(self) -> None:
        """Remove the sandbox unless it was asked to be kept."""
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


def apply_config(config: dict[str, Any]) -> dict[str, Any]:
    """Set the config's AI settings on DocForge; return a description without secrets."""
    from docforge.config import get_settings

    settings = get_settings()
    ai = config.get("ai") or {}
    if not ai.get("enabled"):
        settings.ai_enabled = False
        settings.ai_api_key = ""
        return {"enabled": False}
    raise ConfigError(f"{config['name']}: AI configs arrive in M2 (Haiku 5.5 and LM Studio)")
