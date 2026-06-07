"""Local filesystem storage backend (default; dev + hosts with a persistent disk).

Maps each key to ``base_dir/<key>``. This reproduces DocForge's original on-disk
layout exactly: with ``base_dir = data_dir`` the keys ``uploads/…``,
``templates/…`` and ``generated/…`` land in the same folders as before.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .base import Storage


class LocalStorage(Storage):
    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are trusted (built internally), but guard against escaping base_dir.
        p = (self.base_dir / key).resolve()
        base = self.base_dir.resolve()
        if base not in p.parents and p != base:
            raise ValueError(f"key escapes storage root: {key!r}")
        return p

    def put_bytes(self, key: str, data: bytes, *, content_type: str | None = None) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()

    def list_prefix(self, prefix: str) -> list[str]:
        root = self._path(prefix)
        if not root.exists():
            return []
        base = self.base_dir.resolve()
        if root.is_file():
            return [root.resolve().relative_to(base).as_posix()]
        return [
            p.resolve().relative_to(base).as_posix()
            for p in root.rglob("*")
            if p.is_file()
        ]

    def stat_prefix(self, prefix: str) -> list[tuple[str, int, float | None]]:
        root = self._path(prefix)
        if not root.exists():
            return []
        base = self.base_dir.resolve()
        targets = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        out: list[tuple[str, int, float | None]] = []
        for p in targets:
            try:
                st = p.stat()
            except OSError:
                continue
            out.append((p.resolve().relative_to(base).as_posix(), st.st_size, st.st_mtime))
        return out

    def delete_prefix(self, prefix: str) -> None:
        root = self._path(prefix)
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        # The file already lives on disk — hand it back directly (no copy).
        yield self._path(key)
