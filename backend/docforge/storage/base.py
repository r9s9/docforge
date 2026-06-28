"""Storage abstraction — a small object-store interface DocForge writes through.

Why this exists: DocForge persists three kinds of binary/JSON artifacts —
template-version packages, uploaded source documents, and generated documents.
In local/dev (and on any host with a persistent disk) these live on the
filesystem. On a host *without* a persistent disk (e.g. Render's free tier) they
must live in object storage (Supabase Storage) or they'd vanish on every
restart, leaving the database pointing at files that no longer exist.

Keys are POSIX-style relative paths, e.g. ``templates/<id>/<version>/template.docx``
or ``uploads/<doc_id>.docx``. Backends map keys to a directory or a bucket.

The interface stays deliberately tiny. Crucially it offers ``local_path`` — a
context manager that yields a *real* on-disk path for a key — because a few
consumers (LibreOffice for PDF, python-docx loading by path) need a filesystem
path. For the local backend that's the file itself (zero copy); for a cloud
backend it downloads to a temp file and cleans up afterwards.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


class Storage(ABC):
    """Minimal object-store interface used by the registry and services."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list_prefix(self, prefix: str) -> list[str]:
        """Return all keys under ``prefix`` (recursive, full keys)."""

    @abstractmethod
    def stat_prefix(self, prefix: str) -> list[tuple[str, int, float | None]]:
        """Return ``(key, size_bytes, mtime_epoch_or_None)`` for each key under prefix.

        Used by retention to prune by age/total-size across either backend.
        """

    def delete_prefix(self, prefix: str) -> None:
        """Delete every key under ``prefix`` (best-effort)."""
        for key in self.list_prefix(prefix):
            try:
                self.delete(key)
            except Exception:
                pass

    @abstractmethod
    def local_path(self, key: str) -> AbstractContextManager[Path]:
        """Context manager yielding a real on-disk path for ``key``.

        For remote backends this downloads to a temp file and removes it on exit;
        for the local backend it yields the file in place (no copy).
        """

    # ----- direct browser <-> storage transfer (signed URLs) --------------
    # These let the browser upload/download bytes straight to/from object
    # storage, bypassing the API server entirely. That is essential on hosts
    # with a small request/response body cap (e.g. Vercel Functions cap bodies
    # at 4.5 MB) and is faster everywhere. Backends that can't issue signed URLs
    # (the local filesystem) return ``None``, and callers fall back to streaming
    # the bytes through the API.
    def signed_upload(self, key: str, *, content_type: str | None = None) -> dict | None:
        """A short-lived direct-upload target for ``key``.

        Returns ``{"url": str, "method": "PUT", "headers": {...}}`` the browser
        can use to PUT the file straight into storage, or ``None`` if the backend
        can't (caller should accept a multipart upload instead).
        """
        return None

    def signed_download(
        self, key: str, *, expires_in: int = 3600, filename: str | None = None
    ) -> str | None:
        """A short-lived direct-download URL for ``key``.

        ``filename`` (when given) forces a browser download with that name.
        Returns ``None`` if the backend can't issue one (caller streams instead).
        """
        return None

    # ----- JSON convenience (implemented on top of bytes) -----------------
    def put_json(self, key: str, obj: Any) -> None:
        self.put_bytes(
            key,
            json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
            content_type="application/json",
        )

    def get_json(self, key: str) -> Any:
        return json.loads(self.get_bytes(key).decode("utf-8"))


# Top-level key prefixes (one logical "folder" per artifact kind).
UPLOADS = "uploads"
TEMPLATES = "templates"
GENERATED = "generated"


def join_key(*parts: str) -> str:
    """Join key segments with forward slashes (storage keys are POSIX-style)."""
    return "/".join(p.strip("/") for p in parts if p != "")
