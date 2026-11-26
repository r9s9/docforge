"""The analyze suite's cases: which documents each template is built from (DESIGN.md §5.3).

For each type: its first 1, 2, 3 and 5 examples, in a fixed order, then the shared-value pair
(``ex_01`` and ``shared_02``, which copies one labelled value from it). Pure: it imports no
DocForge code, so the CLI can list the cases before the sandbox exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evals.corpus.build import SHARED_DOC, all_types
from evals.metrics.analyze import KS


@dataclass(frozen=True)
class AnalyzeCase:
    """One template to build: a type and the documents DocForge gets, in order."""

    id: str
    pair: str
    lang: str
    group: str  # "examples" (the first k) or "shared" (ex_01 and shared_02)
    documents: tuple[str, ...]
    shared_field: str | None = None

    @property
    def k(self) -> int:
        return len(self.documents)


def analyze_cases(manifest: dict[str, Any], types: list[str] | None = None,
                  limit: int | None = None) -> list[AnalyzeCase]:
    """Every analyze case, type by type: k = 1, 2, 3, 5, then the shared-value pair.

    ``limit`` keeps the first N cases of each type (``--limit 1`` gives k = 1 only).
    """
    shared = (manifest.get("analyze") or {}).get("shared", {})
    cases: list[AnalyzeCase] = []
    for pair, info in all_types(manifest).items():
        if types and pair not in types:
            continue
        group = [AnalyzeCase(f"{pair}/k{k}", pair, info["lang"], "examples",
                             tuple(info["examples"][:k])) for k in KS]
        if pair in shared:
            group.append(AnalyzeCase(f"{pair}/shared", pair, info["lang"], "shared",
                                     (shared[pair]["copied_from"], SHARED_DOC),
                                     shared[pair]["field"]))
        cases.extend(group[:limit] if limit else group)
    return cases


def document_file(manifest: dict[str, Any], pair: str, name: str) -> str:
    """A document's path in the build directory, as the manifest records it."""
    if name == SHARED_DOC:
        return manifest["analyze"]["shared"][pair]["file"]
    return all_types(manifest)[pair]["documents"][name]["file"]
