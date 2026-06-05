"""Generated-file retention (spec §19: temporary file cleanup).

Prunes ``data/generated`` by age and by total-size cap. Called on startup and
after each generation so output files don't accumulate without bound.
"""

from __future__ import annotations

import logging
import time

from ..config import Settings, get_settings

logger = logging.getLogger("docforge.retention")


def prune_generated(settings: Settings | None = None) -> int:
    """Delete old / excess generated files. Returns the number removed."""
    settings = settings or get_settings()
    directory = settings.generated_dir
    if not directory.exists():
        return 0

    now = time.time()
    max_age = settings.generated_retention_days * 86400
    cap = settings.generated_max_total_mb * 1024 * 1024

    files: list[tuple] = []
    for p in directory.iterdir():
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        files.append((p, st.st_mtime, st.st_size))

    removed = 0

    # 1) Age-based pruning.
    if max_age:
        for entry in list(files):
            p, mtime, _size = entry
            if now - mtime > max_age:
                try:
                    p.unlink()
                    removed += 1
                    files.remove(entry)
                except OSError:
                    pass

    # 2) Size-based pruning: delete oldest first until under the cap.
    if cap:
        total = sum(s for _, _, s in files)
        for p, _mtime, size in sorted(files, key=lambda x: x[1]):
            if total <= cap:
                break
            try:
                p.unlink()
                removed += 1
                total -= size
            except OSError:
                pass

    if removed:
        logger.info("Pruned %d generated file(s) from %s", removed, directory)
    return removed
