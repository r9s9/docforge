"""Building blocks of a document-type spec.

A spec is an ordered list of blocks. Blocks whose text is the same in every document of the type
(title, headings, clauses, fixed lines) become DocForge boilerplate; blocks whose value changes
per document (fields, free text, tables) become template fields. An information block mixes the
two, cell by cell: fixed labels next to values that change. The generator turns a spec and a
document index into a .docx and its ground truth.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Title:
    """The document title: centred, bold, 18 pt. The same in every document."""

    id: str
    text: str


@dataclass(frozen=True)
class Field:
    """A labelled paragraph whose value changes per document: ``Invoice Date: 14 March 2026``."""

    id: str
    label: str
    key: str
    field_type: str  # text | date | money | number | person
    required: bool = True


@dataclass(frozen=True)
class FixedLine:
    """A labelled paragraph whose value is the same in every document: ``Supplier: ...``."""

    id: str
    label: str
    text: str


@dataclass(frozen=True)
class Heading:
    """A Word heading (style ``Heading <level>``). The same in every document."""

    id: str
    text: str
    level: int = 1


@dataclass(frozen=True)
class Clause:
    """A boilerplate paragraph, identical in every document of the type."""

    id: str
    text: str
    material: bool = True  # does changing or removing it matter?


@dataclass(frozen=True)
class FreeText:
    """A paragraph with no label whose whole text changes per document."""

    id: str
    key: str


@dataclass(frozen=True)
class TableBlock:
    """A table with a bold header row and data rows that change per document."""

    id: str
    headers: tuple[str, ...]
    key: str
    row_removal_material: bool = True


@dataclass(frozen=True)
class InfoRow:
    """One row of an information block: a fixed label, and a value that changes or not.

    ``id`` names the value cell; the label cell is ``<id>.label``. A row with ``key`` takes its
    value from the value set (a field of type ``field_type``); a row with ``text`` has the same
    value in every document (boilerplate).
    """

    id: str
    label: str
    key: str | None = None
    text: str | None = None
    field_type: str = "text"


@dataclass(frozen=True)
class InfoTable:
    """A "label | value" table without a header row, such as a document-control block.

    Every row is something different (reference, version, owner), so the table is a form to
    fill, not a list that repeats. Its first row is what DocForge aligns tables on.
    """

    id: str
    rows: tuple[InfoRow, ...]


Block = Title | Field | FixedLine | Heading | Clause | FreeText | TableBlock | InfoTable


@dataclass(frozen=True)
class DocTypeSpec:
    """One document type in one language, e.g. ``service_agreement_de``."""

    pair: str
    doc_type: str
    lang: str  # en | de
    blocks: tuple[Block, ...]
    footer: str  # footer text in front of the PAGE field
    values: Callable[[int], dict[str, Any]]  # document index -> value set
    mutations: dict[str, dict[str, Any]] = field(default_factory=dict)

    def block_ids(self) -> list[str]:
        """Logical IDs of every block, in document order."""
        return [b.id for b in self.blocks]
