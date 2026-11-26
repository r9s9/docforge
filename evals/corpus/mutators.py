"""Mutation library: each mutator injects one labelled deviation into a clean document.

A mutator takes a clean .docx, its ground truth and its spec, and returns the mutated .docx and
a label saying what changed, which DocForge difference kind the brief expects (DESIGN.md §4.3),
and whether the change is material. Targets are found with DocForge's own walk (through the
ground-truth locators) and edited as python-docx objects; everything else in the document is
left exactly as it was, which ``tests/evals/test_mutators.py`` checks.

The parameters of each mutation (which clause, which words) live in the document-type spec, so
a mutator applies only where the spec defines it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from docx import Document
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from evals.corpus.generator import docx_bytes
from evals.corpus.ground_truth import top_level_nodes
from evals.corpus.model import DocTypeSpec
from evals.corpus.values import parse_date

Label = dict[str, Any]


class MutationError(ValueError):
    """A mutation can't be applied as the spec describes it."""


class _Context:
    """The parsed document plus helpers to reach elements by logical ID."""

    def __init__(self, data: bytes, truth: list[dict[str, Any]], spec: DocTypeSpec):
        self.doc = Document(BytesIO(data))
        self.spec = spec
        self.truth = {element["id"]: element for element in truth}
        self._nodes = top_level_nodes(self.doc)

    def node(self, logical_id: str):
        locator = self.truth[logical_id]["locator"]
        return self._nodes[(locator["scope"], locator["block"])]

    def paragraph(self, logical_id: str) -> Paragraph:
        node = self.node(logical_id)
        if node.kind != "paragraph":
            raise MutationError(f"{logical_id} is not a paragraph")
        return node.obj

    def table(self, logical_id: str):
        node = self.node(logical_id)
        if node.kind != "table":
            raise MutationError(f"{logical_id} is not a table")
        return node.obj


@dataclass(frozen=True)
class Mutator:
    """How to apply one kind of deviation, and what the brief expects DocForge to report."""

    apply: Callable[[_Context, dict[str, Any]], dict[str, Any]]
    expected_kind: str | None  # DocForge difference kind; None = no difference expected
    material: bool | None  # None = taken from the target's ground truth
    fixable: bool = False  # a changed or missing FIXED paragraph, which fix_document repairs
    rule_dependent: bool = False


# --- edits ---------------------------------------------------------------------------------


def _replace_in_runs(paragraph: Paragraph, old: str, new: str) -> None:
    for run in paragraph.runs:
        if old in run.text:
            run.text = run.text.replace(old, new, 1)
            return
    raise MutationError(f"{old!r} not found in a single run of {paragraph.text!r}")


def _set_value(paragraph: Paragraph, value: str) -> None:
    """Replace a labelled paragraph's value, keeping the bold label run."""
    _label, *rest = paragraph.runs
    if not rest:
        raise MutationError(f"no value run in {paragraph.text!r}")
    rest[0].text = value
    for run in rest[1:]:
        run.text = ""


def _remove(element) -> None:
    element.getparent().remove(element)


# --- mutators ------------------------------------------------------------------------------


def _replace_text(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    paragraph = ctx.paragraph(params["target"])
    before = paragraph.text
    for old, new in params["replace"]:
        _replace_in_runs(paragraph, old, new)
    return {"before": before, "after": paragraph.text}


def _delete_elements(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    removed = [ctx.paragraph(target).text for target in params["targets"]]
    for target in params["targets"]:
        _remove(ctx.paragraph(target)._p)
    return {"removed": removed}


def _upper_case(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    paragraph = ctx.paragraph(params["target"])
    before = paragraph.text
    for run in paragraph.runs:
        run.text = run.text.upper()
    return {"before": before, "after": paragraph.text}


def _empty_field(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    before = ctx.truth[params["target"]]["value"]
    _set_value(ctx.paragraph(params["target"]), "")
    return {"before": before, "after": ""}


def _iso_date(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    before = ctx.truth[params["target"]]["value"]
    after = parse_date(before, ctx.spec.lang).isoformat()
    _set_value(ctx.paragraph(params["target"]), after)
    return {"before": before, "after": after}


def _invalid_value(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    before = ctx.truth[params["target"]]["value"]
    _set_value(ctx.paragraph(params["target"]), params["value"])
    return {"before": before, "after": params["value"]}


def _remove_row(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    table = ctx.table(params["target"])
    if len(table.rows) < 3:
        raise MutationError("a row is only removed from a table with two or more data rows")
    removed = [cell.text for cell in table.rows[-1].cells]
    _remove(table.rows[-1]._tr)
    return {"removed_row": removed, "rows_left": len(table.rows) - 1}


def _remove_column(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    table, column = ctx.table(params["target"]), params["column"]
    header = table.rows[0].cells[column].text
    for row in table.rows:
        _remove(row._tr.tc_lst[column])
    _remove(table._tbl.tblGrid.gridCol_lst[column])
    return {"removed_column": header}


def _delete_table(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    table = ctx.table(params["target"])
    _remove(table._tbl)
    return {"removed_table": ctx.truth[params["target"]]["headers"]}


def _reorder(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    first = [ctx.paragraph(target)._p for target in params["first"]]
    anchor = ctx.paragraph(params["second"][-1])._p
    for element in reversed(first):
        anchor.addnext(element)  # moves the element: first section now follows the second
    return {"moved": params["first"], "after": params["second"][-1]}


def _insert(ctx: _Context, params: dict[str, Any]) -> dict[str, Any]:
    anchor = ctx.paragraph(params["after"])
    new = OxmlElement("w:p")
    anchor._p.addnext(new)
    Paragraph(new, anchor._parent).add_run(params["text"])
    return {"after": params["after"], "text": params["text"]}


MUTATORS: dict[str, Mutator] = {
    "change_liability_cap": Mutator(_replace_text, "changed_fixed", True, fixable=True),
    "change_governing_law": Mutator(_replace_text, "changed_fixed", True, fixable=True),
    "change_notice_period": Mutator(_replace_text, "changed_fixed", True, fixable=True),
    "change_payment_terms": Mutator(_replace_text, "changed_fixed", True, fixable=True),
    "delete_clause": Mutator(_delete_elements, "missing_fixed", None, fixable=True),
    "fix_typo": Mutator(_replace_text, "changed_fixed", False, fixable=True),
    "whitespace_quotes": Mutator(_replace_text, "changed_fixed", False, fixable=True),
    "heading_caps": Mutator(_upper_case, "changed_fixed", False, fixable=True),
    "empty_field": Mutator(_empty_field, "missing_field", True),
    "date_format": Mutator(_iso_date, "format", False, rule_dependent=True),
    "invalid_value": Mutator(_invalid_value, "format", True),
    "remove_row": Mutator(_remove_row, "table_shape", None),
    "remove_column": Mutator(_remove_column, "table_shape", True),
    "delete_table": Mutator(_delete_table, "missing_table", True),
    "reorder_sections": Mutator(_reorder, None, False),
    "insert_benign": Mutator(_insert, None, False),
    "insert_material": Mutator(_insert, None, True),
}


def applicable(spec: DocTypeSpec) -> list[str]:
    """The mutators a document type defines parameters for, in library order."""
    return [name for name in MUTATORS if name in spec.mutations]


def _targets(params: dict[str, Any]) -> list[str]:
    if "target" in params:
        return [params["target"]]
    if "targets" in params:
        return list(params["targets"])
    if "first" in params:
        return [*params["first"], *params["second"]]
    return []  # inserts: the new paragraph has no place in the template


def _material(mutator: Mutator, targets: list[str], truth: dict[str, dict[str, Any]]) -> bool:
    if mutator.material is not None:
        return mutator.material
    return any(
        truth[target].get("material_if_changed", truth[target].get("row_removal_material"))
        for target in targets
    )


def mutate(
    name: str, data: bytes, truth: list[dict[str, Any]], spec: DocTypeSpec
) -> tuple[bytes, Label]:
    """Apply mutator ``name`` to a clean document; return the mutated bytes and the label."""
    mutator, params = MUTATORS[name], spec.mutations[name]
    ctx = _Context(data, truth, spec)
    detail = mutator.apply(ctx, params)
    targets = _targets(params)
    label: Label = {
        "mutator": name,
        "targets": targets,
        "expected_kind": mutator.expected_kind,
        "material": _material(mutator, targets, ctx.truth),
        "rule_dependent": mutator.rule_dependent,
        "fixable": mutator.fixable,
        "detail": detail,
    }
    return docx_bytes(ctx.doc), label


def clean_label() -> Label:
    """The label of an unmodified held-out document (a clean control)."""
    return {
        "mutator": "none",
        "targets": [],
        "expected_kind": None,
        "material": False,
        "rule_dependent": False,
        "fixable": False,
        "detail": {},
    }
