"""Supabase Storage backend — object storage over the Storage REST API.

Used in production on disk-less hosts. Talks to Supabase Storage directly with
httpx (no extra SDK) using the project's *service-role* key, which bypasses RLS
so the server has full read/write to its bucket. The service-role key is a
server-side secret and must never reach the browser.

API reference (relative to ``{supabase_url}/storage/v1``):
  PUT    /object/{bucket}/{key}        upload (x-upsert: true to overwrite)
  GET    /object/{bucket}/{key}        download
  DELETE /object/{bucket}/{key}        delete one
  POST   /object/list/{bucket}         list a prefix (one level)
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from .base import Storage

logger = logging.getLogger("docforge.storage.supabase")

_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _parse_ts(value: str | None) -> float | None:
    """Parse a Supabase ISO-8601 timestamp (e.g. '2024-01-01T00:00:00.000Z') to epoch."""
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


class SupabaseStorage(Storage):
    def __init__(self, url: str, service_key: str, bucket: str, *, timeout: float = 30.0):
        if not url or not service_key:
            raise ValueError("Supabase storage requires supabase_url and a service-role key")
        self.base = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self._headers = {
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
        }
        self._client = httpx.Client(timeout=timeout, headers=self._headers)

    # ----- core ops -------------------------------------------------------
    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        r = self._client.put(
            f"{self.base}/object/{self.bucket}/{key}",
            content=data,
            headers={"content-type": content_type or _DEFAULT_CONTENT_TYPE, "x-upsert": "true"},
        )
        if r.status_code not in (200, 201):
            raise OSError(f"storage put failed for {key!r}: {r.status_code} {r.text[:300]}")

    def get_bytes(self, key: str) -> bytes:
        r = self._client.get(f"{self.base}/object/{self.bucket}/{key}")
        if r.status_code == 200:
            return r.content
        if r.status_code in (400, 404):
            raise FileNotFoundError(f"storage key not found: {key!r}")
        raise OSError(f"storage get failed for {key!r}: {r.status_code} {r.text[:300]}")

    def exists(self, key: str) -> bool:
        # A ranged GET fetches almost nothing but reliably tells us if it's there.
        # Only a genuine not-found means "absent"; any other error (5xx/401/403/
        # 429) must surface, not masquerade as a missing file (a transient error
        # mis-read as "absent" could, e.g., drop a source doc from a manifest).
        r = self._client.get(
            f"{self.base}/object/{self.bucket}/{key}", headers={"Range": "bytes=0-0"}
        )
        if r.status_code in (200, 206):
            return True
        if r.status_code in (400, 404):
            return False
        raise OSError(f"storage exists check failed for {key!r}: {r.status_code} {r.text[:300]}")

    def delete(self, key: str) -> None:
        r = self._client.delete(f"{self.base}/object/{self.bucket}/{key}")
        if r.status_code not in (200, 404):
            raise OSError(f"storage delete failed for {key!r}: {r.status_code} {r.text[:300]}")

    def list_prefix(self, prefix: str) -> list[str]:
        """Recursively list full keys under ``prefix``."""
        return [e[0] for e in self._walk(prefix.strip("/"))]

    def stat_prefix(self, prefix: str) -> list[tuple[str, int, float | None]]:
        return self._walk(prefix.strip("/"))

    def _walk(self, prefix: str, *, _depth: int = 0) -> list[tuple[str, int, float | None]]:
        """Recursively enumerate (key, size, mtime) under ``prefix``.

        Supabase ``list`` returns one directory level: file entries have a
        non-null ``id`` (and carry ``metadata.size`` + ``updated_at``); sub-folder
        entries have ``id == null``. We page through each level (the endpoint caps
        at ~1000 rows/call) and recurse into folders for the full key set.
        """
        if _depth > 12:  # safety against pathological nesting
            return []
        out: list[tuple[str, int, float | None]] = []
        offset = 0
        page = 1000
        while True:
            body = {
                "prefix": (prefix + "/") if prefix else "",
                "limit": page,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            }
            r = self._client.post(f"{self.base}/object/list/{self.bucket}", json=body)
            if r.status_code != 200:
                logger.debug("storage list failed for %r: %s", prefix, r.status_code)
                break
            rows = r.json()
            if not rows:
                break
            for entry in rows:
                name = entry.get("name")
                if not name:
                    continue
                full = f"{prefix}/{name}" if prefix else name
                if entry.get("id") is None:
                    out.extend(self._walk(full, _depth=_depth + 1))
                else:
                    meta = entry.get("metadata") or {}
                    size = int(meta.get("size") or 0)
                    mtime = _parse_ts(entry.get("updated_at") or entry.get("created_at"))
                    out.append((full, size, mtime))
            if len(rows) < page:  # last page
                break
            offset += len(rows)
        return out

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        data = self.get_bytes(key)
        suffix = Path(key).suffix or ".bin"
        fd, name = tempfile.mkstemp(suffix=suffix, prefix="docforge-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            yield Path(name)
        finally:
            try:
                os.unlink(name)
            except OSError:
                pass
