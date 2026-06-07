"""Storage layer: a tiny object-store interface with local + Supabase backends.

Use ``get_storage()`` everywhere; the concrete backend is chosen by
``settings.storage_backend``. See ``base.Storage`` for the rationale.
"""

from __future__ import annotations

from ..config import get_settings
from .base import GENERATED, TEMPLATES, UPLOADS, Storage, join_key
from .local import LocalStorage

__all__ = [
    "Storage",
    "get_storage",
    "join_key",
    "UPLOADS",
    "TEMPLATES",
    "GENERATED",
]

# Cache backends by their resolved config key. We intentionally do NOT use a
# blanket singleton: tests monkeypatch ``settings.data_dir`` per test, and the
# local backend captures that dir at construction — so the cache key must include
# it. In production the key is stable, so the (httpx-client-holding) Supabase
# backend is built once and reused.
_cache: dict[tuple, Storage] = {}


def get_storage() -> Storage:
    """Return the storage backend selected by settings (cached per config)."""
    s = get_settings()
    if s.storage_backend == "supabase":
        key = ("supabase", s.supabase_url, s.supabase_storage_bucket)
        if key not in _cache:
            from .supabase import SupabaseStorage

            _cache[key] = SupabaseStorage(
                url=s.supabase_url,
                service_key=s.supabase_service_role_key,
                bucket=s.supabase_storage_bucket,
            )
        return _cache[key]

    # Default: local filesystem rooted at the data dir, so keys map to the
    # original uploads/ templates/ generated/ folders.
    s.ensure_dirs()
    key = ("local", str(s.data_dir))
    if key not in _cache:
        _cache[key] = LocalStorage(s.data_dir)
    return _cache[key]
