"""Central application configuration.

All settings are environment-driven (12-factor). Secrets such as the AI API key
are ONLY ever read from the environment — never hardcoded or logged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, populated from environment variables / .env file.

    Env vars are prefixed with ``DOCFORGE_`` (e.g. ``DOCFORGE_DATA_DIR``).
    """

    model_config = SettingsConfigDict(
        env_prefix="DOCFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    env: str = "development"
    debug: bool = True
    data_dir: Path = Path("./data")
    database_url: str = "sqlite:///./data/docforge.db"

    # --- Uploads / safety ---
    max_upload_mb: int = 25
    max_files_per_analysis: int = 5
    zip_max_total_mb: int = 200  # zip-bomb guard (uncompressed)
    zip_max_entries: int = 2000  # zip-bomb guard (entry count)

    # --- Generated-file retention (spec §19: temporary file cleanup) ---
    generated_retention_days: int = 14  # delete generated docs older than this
    generated_max_total_mb: int = 500  # cap total size; prune oldest beyond it

    # --- AI provider ---
    # provider: "openai" (OpenAI / local OpenAI-compatible) or "anthropic".
    ai_provider: str = "openai"
    ai_enabled: bool = False
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: int = 240  # generous for slow local models (background work)
    # Shorter cap for tiny in-request calls (e.g. the Settings "test connection").
    ai_interactive_timeout_seconds: int = 90
    # Document/raw routing in the Generate tab sends a large prompt (the whole
    # document + all template fields) to a local model, which can take a few
    # minutes — give it a real budget instead of falling back to heuristics early.
    ai_generation_timeout_seconds: int = 300
    ai_max_retries: int = 2
    ai_max_output_tokens: int = 6000

    # --- Auth (Supabase) ---
    # When auth_required, API data routes require a valid Supabase JWT (verified
    # locally with the project's JWT secret) and scope all data to that user.
    auth_required: bool = True
    supabase_url: str = ""
    supabase_jwt_secret: str = ""  # Supabase project JWT secret (HS256)
    supabase_jwt_audience: str = "authenticated"
    # Comma-separated allowed CORS origins (the deployed frontend). "*" allows all.
    cors_allow_origins: str = "*"

    # --- Logging ---
    log_level: str = "INFO"
    log_redact: bool = True

    # --- Derived paths (computed, not from env) ---
    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def generated_dir(self) -> Path:
        return self.data_dir / "generated"

    @property
    def extractions_dir(self) -> Path:
        return self.data_dir / "extractions"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def zip_max_total_bytes(self) -> int:
        return self.zip_max_total_mb * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        """Allowed CORS origins as a list (``*`` -> allow all)."""
        raw = (self.cors_allow_origins or "*").strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def ai_active(self) -> bool:
        """AI is only *active* when explicitly enabled AND a key/base is present.

        When inactive, the platform uses deterministic heuristic fallbacks so it
        runs fully offline with no external calls (local-first / privacy-aware).
        """
        return self.ai_enabled and bool(self.ai_api_key) and bool(self.ai_base_url)

    def ensure_dirs(self) -> None:
        """Create the runtime data directories if they don't exist."""
        for d in (
            self.data_dir,
            self.uploads_dir,
            self.templates_dir,
            self.generated_dir,
            self.extractions_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (one instance per process)."""
    return Settings()
