"""Rough notes for the generate suite, and the values a correct document holds (DESIGN.md §4.4).

One YAML file per case, ``evals/corpus/notes/<pair>/<style>.yaml``::

    style: email          # bullets | email | mixed | missing | correction
    source: held_02       # the held-out document whose values the notes carry
    text: |               # the notes, as a user would paste them
      ...
    expected:             # every field of the type, by logical ID
      field.date: 13 March 2026                  # a value the notes give
      field.vat_id: null                         # the notes don't give it
      field.meeting: {value: ..., accept: [...]} # more than one right answer
      text.services: {points: [...]}             # free text: what a faithful, complete value covers
      table.fees: {rows: [[...], ...]}           # a cell may be null, or a list of right answers
    superseded:           # correction cases only: the values the notes later correct
      field.monthly_fee: €14,500.00

The notes are written by hand from the held-out documents' values, so every person and company
in them is one of the invented ones in NAMES.md. ``problems`` checks each case against those
values and against its own text.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from evals.corpus.doc_types import SPECS
from evals.corpus.generator import EXAMPLES, HELD_OUT, doc_id
from evals.corpus.model import Field, FreeText, TableBlock
from evals.metrics.normalize import appears_in, appears_in_cell, norm_text, same, same_cell
from evals.paths import CORPUS_DIR

NOTES_DIR = CORPUS_DIR / "notes"
STYLES = ("bullets", "email", "mixed", "missing", "correction")

# How each logical field is compared. A Field's own type, except where its value is a list of
# people, or a phrase a writer may rightly rephrase (then the rubric grader judges it).
KIND_OVERRIDES = {"field.attendees": "names", "field.purpose": "free"}
TABLE_COLUMNS = {
    "table.items": ("text", "number", "money", "money"),
    "table.fees": ("text", "text", "money"),
    "table.actions": ("text", "person", "date"),
}


@dataclass(frozen=True)
class NotesCase:
    """One notes text and the document it should produce."""

    id: str  # "<pair>/<style>"
    pair: str
    style: str
    source: str
    text: str
    expected: dict[str, dict[str, Any]]
    superseded: dict[str, str]
    path: Path


def field_kinds(pair: str) -> dict[str, str]:
    """Logical field ID → kind (text, date, money, number, person, names, free, table)."""
    kinds: dict[str, str] = {}
    for block in SPECS[pair].blocks:
        if isinstance(block, Field):
            kinds[block.id] = KIND_OVERRIDES.get(block.id, block.field_type)
        elif isinstance(block, FreeText):
            kinds[block.id] = "free"
        elif isinstance(block, TableBlock):
            kinds[block.id] = "table"
    return kinds


def source_values(pair: str, source: str) -> dict[str, Any]:
    """The source document's value for every logical field, by logical ID."""
    names = {doc_id(EXAMPLES + i): EXAMPLES + i for i in range(HELD_OUT)}
    values = SPECS[pair].values(names[source])
    keys = {block.id: block.key for block in SPECS[pair].blocks
            if isinstance(block, (Field, FreeText, TableBlock))}
    return {logical: values[key] for logical, key in keys.items()}


def _cells(cell: Any) -> list[str] | None:
    if cell is None:
        return None
    return [str(c) for c in cell] if isinstance(cell, list) else [str(cell)]


def _expectation(kind: str, raw: Any) -> dict[str, Any]:
    if kind == "free":
        return {"kind": kind, "points": (raw or {}).get("points") if raw is not None else None}
    if kind == "table":
        if raw is None:
            return {"kind": kind, "rows": None}
        rows = [[_cells(cell) for cell in row] for row in raw["rows"]]
        return {"kind": kind, "rows": rows}
    if isinstance(raw, dict):
        return {"kind": kind, "value": raw.get("value"), "accept": list(raw.get("accept") or [])}
    return {"kind": kind, "value": None if raw is None else str(raw), "accept": []}


def load_case(path: Path) -> NotesCase:
    """Read one notes file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    pair = Path(path).parent.name
    kinds = field_kinds(pair)
    expected = {logical: _expectation(kinds.get(logical, "text"), raw)
                for logical, raw in (data.get("expected") or {}).items()}
    for logical, expectation in expected.items():
        if expectation["kind"] == "table":
            expectation["columns"] = TABLE_COLUMNS.get(logical, ())
    return NotesCase(
        id=f"{pair}/{Path(path).stem}",
        pair=pair,
        style=str(data.get("style", "")),
        source=str(data.get("source", "")),
        text=str(data.get("text", "")),
        expected=expected,
        superseded={k: str(v) for k, v in (data.get("superseded") or {}).items()},
        path=Path(path),
    )


def load_notes(pairs: list[str] | None = None, root: Path = NOTES_DIR) -> list[NotesCase]:
    """Every notes case, by pair (in corpus order) and style."""
    cases = []
    for pair in SPECS:
        if pairs and pair not in pairs:
            continue
        for style in STYLES:
            path = root / pair / f"{style}.yaml"
            if path.exists():
                cases.append(load_case(path))
    return cases


def problems(case: NotesCase) -> list[str]:
    """Everything wrong with a notes case; empty when it is consistent."""
    issues: list[str] = []
    kinds = field_kinds(case.pair)
    if case.style not in STYLES or case.style != case.path.stem:
        issues.append(f"style {case.style!r} doesn't match the file name {case.path.name}")
    try:
        source = source_values(case.pair, case.source)
    except KeyError:
        return issues + [f"source {case.source!r} is not a held-out document"]
    if set(case.expected) != set(kinds):
        missing, extra = set(kinds) - set(case.expected), set(case.expected) - set(kinds)
        issues.append(f"expected must list every field: missing {sorted(missing)}, "
                      f"unknown {sorted(extra)}")
    for logical, expectation in case.expected.items():
        if logical in kinds:
            issues += [f"{logical}: {issue}" for issue in
                       _field_problems(kinds[logical], expectation, source[logical], case.text)]
    for logical, value in case.superseded.items():
        expectation = case.expected.get(logical) or {}
        kind = kinds.get(logical, "text")
        if not appears_in(kind, value, case.text):
            issues.append(f"{logical}: superseded {value!r} is not in the notes")
        if any(same(kind, value, right) for right in
               [expectation.get("value"), *expectation.get("accept", [])]):
            issues.append(f"{logical}: superseded {value!r} is also a right answer")
    if (case.style == "correction") != bool(case.superseded):
        issues.append("only a correction case lists superseded values, and it must")
    if case.style == "missing" and not any(
        e.get("value", e.get("points", e.get("rows", ""))) is None for e in case.expected.values()
    ):
        issues.append("a missing-information case leaves at least one field out")
    return issues


def _field_problems(kind: str, expectation: dict[str, Any], source: Any, text: str) -> list[str]:
    if kind == "free":
        points = expectation["points"]
        if points is None:
            return ["its source text is in the notes, but it is null"] if (
                norm_text(source) in norm_text(text)) else []
        if not points or not all(isinstance(p, str) and p.strip() for p in points):
            return ["points must be a non-empty list of strings"]
        return []
    if kind == "table":
        return _table_problems(expectation, source, text)
    value, issues = expectation["value"], []
    if value is None:
        if appears_in(kind, source, text):
            issues.append(f"null, but the source value {source!r} is in the notes")
        return issues
    if not same(kind, value, source):
        issues.append(f"{value!r} differs from the source document's {source!r}")
    if not (appears_in(kind, value, text)
            or any(appears_in(kind, alt, text) for alt in expectation["accept"])):
        issues.append(f"neither {value!r} nor an accepted form is in the notes")
    return issues


def _table_problems(expectation: dict[str, Any], source: list[list[str]], text: str) -> list[str]:
    rows, columns = expectation["rows"], expectation["columns"]
    if rows is None:
        return []
    issues = []
    if len(rows) != len(source):
        issues.append(f"{len(rows)} rows, the source document has {len(source)}")
    for r, (row, source_row) in enumerate(zip(rows, source, strict=False)):
        if len(row) != len(columns):
            issues.append(f"row {r + 1} has {len(row)} cells for {len(columns)} columns")
            continue
        for c, (cell, kind, truth) in enumerate(zip(row, columns, source_row, strict=True)):
            if cell is None:
                continue
            if not any(same_cell(kind, alt, truth) for alt in cell):
                issues.append(f"row {r + 1} cell {c + 1}: {cell} differs from {truth!r}")
            if not appears_in_cell(kind, cell[0], text):
                issues.append(f"row {r + 1} cell {c + 1}: {cell[0]!r} is not in the notes")
    return issues
