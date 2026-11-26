"""JSON formatting for committed files (the manifest and result files).

Nested objects are indented, but each object inside a list sits on one line. Documents, cases
and per-case results then take one line each, which keeps diffs of committed files readable.
"""

from __future__ import annotations

import json
from typing import Any


def dumps(value: Any, depth: int = 0) -> str:
    """Format ``value`` as described above (no trailing newline)."""
    pad = " " * depth
    if isinstance(value, dict) and value:
        items = [f"{pad} {json.dumps(k)}: {dumps(v, depth + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        lines = [f"{pad} {json.dumps(v, ensure_ascii=False)}" for v in value]
        return "[\n" + ",\n".join(lines) + "\n" + pad + "]"
    return json.dumps(value, ensure_ascii=False)
