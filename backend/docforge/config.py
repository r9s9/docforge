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
    # Serverless hosting (e.g. Vercel Functions): the process is short-lived and
    # frozen after each response, so background threads can't finish and per-boot
    # maintenance is wasteful. When true: analysis runs synchronously in-request,
    # and table creation + startup maintenance are skipped (run migrations out of
    # band). Defaults off for the long-running server / local dev.
    serverless: bool = False

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

    # --- Free-tier AI (shared, server-side key; never exposed to users) ---
    # A small allowance of AI actions every signed-in user gets for free, served
    # by a shared key the platform owner pays for (e.g. a cheap Claude Haiku key).
    # Users never see this key. Once a user spends ``free_ai_limit`` actions they
    # must add their OWN key (Settings -> AI) to keep using AI; otherwise the app
    # falls back to the offline heuristic engine. When ``free_ai_enabled`` is on,
    # the free tier supersedes the global ``ai_*`` key for users without their own.
    free_ai_enabled: bool = False
    free_ai_provider: str = "anthropic"  # "openai" | "anthropic"
    free_ai_base_url: str = "https://api.anthropic.com"
    free_ai_model: str = "claude-haiku-4-5-20251001"
    free_ai_api_key: str = ""
    free_ai_limit: int = 10  # free AI actions per user

    # --- Auth (Supabase) ---
    # When auth_required, API data routes require a valid Supabase JWT (verified
    # locally with the project's JWT secret) and scope all data to that user.
    auth_required: bool = True
    supabase_url: str = ""
    supabase_jwt_secret: str = ""  # Supabase project JWT secret (HS256)
    supabase_jwt_audience: str = "authenticated"
    # Comma-separated allowed CORS origins (the deployed frontend). "*" allows all.
    cors_allow_origins: str = "*"

    # --- File storage ---
    # "local" keeps template packages / uploads / generated docs on the local
    # filesystem (dev, and any host with a persistent disk). "supabase" stores
    # them in a Supabase Storage bucket — required when the host has no
    # persistent disk (e.g. Render's free tier), so files survive restarts.
    storage_backend: str = "local"  # "local" | "supabase"
    # Service-role key (server-side ONLY — never exposed to the browser). Used to
    # read/write the storage bucket, bypassing RLS.
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "docforge"

    # --- Logging ---
    log_level: str = "INFO"
    log_redact: bool = True
    # Optional path to also write logs to a file (rotating). Empty = console only.
    # Handy for troubleshooting a deployed instance: set DOCFORGE_LOG_FILE=/tmp/docforge.log
    log_file: str = ""

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
        """Allowed CORS origins as a list (``*`` -> allow all).

        Trailing slashes are stripped: a browser's ``Origin`` header never has a
        path/slash (e.g. ``https://app.vercel.app``), but it's easy to paste the
        address-bar URL with one (``https://app.vercel.app/``) into the env var —
        which would silently never match. Normalizing here avoids that footgun.
        """
        raw = (self.cors_allow_origins or "*").strip()
        if raw == "*":
            return ["*"]
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]

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
