"""Generated-file retention (spec §19: temporary file cleanup).

Prunes generated documents by age and by total-size cap. Operates through the
storage layer, so it works on BOTH the local-disk and Supabase backends (on a
disk-less host the files live in the bucket — pruning the local dir would be a
no-op and the bucket would grow without bound). Called on startup and after each
generation so outputs don't accumulate forever.
"""

from __future__ import annotations

import logging
import time

from ..config import Settings, get_settings
from ..storage import GENERATED, get_storage

logger = logging.getLogger("docforge.retention")


def prune_generated(settings: Settings | None = None) -> int:
    """Delete old / excess generated files. Returns the number removed."""
    settings = settings or get_settings()
    storage = get_storage()

    now = time.time()
    max_age = settings.generated_retention_days * 86400
    cap = settings.generated_max_total_mb * 1024 * 1024

    # (key, size, mtime) for every generated object, in either backend.
    entries = storage.stat_prefix(GENERATED + "/")
    removed = 0

    # 1) Age-based pruning (skip entries with unknown mtime).
    if max_age:
        for entry in list(entries):
            _key, _size, mtime = entry
            if mtime and now - mtime > max_age:
                try:
                    storage.delete(_key)
                    removed += 1
                    entries.remove(entry)
                except Exception:
                    logger.debug("retention delete failed for %s", _key, exc_info=True)

    # 2) Size-based pruning: delete oldest first until under the cap.
    if cap:
        total = sum(size for _, size, _ in entries)
        for key, size, _mtime in sorted(entries, key=lambda x: x[2] or 0.0):
            if total <= cap:
                break
            try:
                storage.delete(key)
                removed += 1
                total -= size
            except Exception:
                logger.debug("retention delete failed for %s", key, exc_info=True)

    if removed:
        logger.info("Pruned %d generated file(s)", removed)
    return removed
