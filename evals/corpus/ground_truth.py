"""Resolve ground-truth locators to DocForge node IDs.

DocForge numbers a document's paragraphs and tables in the order of its own walk
(``docforge.structure_normalizer.walk_document``): ``n0001``, ``n0002``, ... The corpus records
each element's place as a locator instead (scope + block index), so it doesn't depend on that
numbering. Here a locator is turned into the node ID DocForge gives that element, and the text
is checked, so a mismatch fails loudly instead of skewing a metric.

Only DocForge's pure walk is imported; it loads neither settings nor a database.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document

from docforge.structure_normalizer import walk_document


class GroundTruthError(ValueError):
    """A locator points nowhere, or at an element whose text isn't the expected one."""


def normalize_text(text: str) -> str:
    """Collapse runs of whitespace, so cosmetic spacing doesn't break a comparison."""
    return " ".join((text or "").split())


def top_level_nodes(doc) -> dict[tuple[str, int], Any]:
    """Top-level walk nodes keyed by (scope, block index); body scope is ``"body"``."""
    return {
        (node.scope or "body", node.position_index): node
        for node in walk_document(doc)
        if node.parent_node_id is None
    }


def node_text(node) -> str:
    """A node's text: a paragraph's text, or a table's header row joined with `` | ``."""
    if node.kind == "table":
        return " | ".join(cell.text for cell in node.obj.rows[0].cells)
    return node.obj.text


def element_text(element: dict[str, Any]) -> str:
    """The text the ground truth expects at an element's locator."""
    if element["kind"] == "table":
        return " | ".join(element["headers"])
    return element["text"]


def skeleton(data: bytes) -> list[tuple]:
    """Top-level elements in walk order: (scope, kind, text or table cells, style).

    Two documents with equal skeletons have the same paragraphs, tables, cell texts and
    paragraph styles in the same order. Used to check that a fixed document is back to its
    clean original, and by the mutator tests.
    """
    items: list[tuple] = []
    for node in walk_document(Document(BytesIO(data))):
        if node.parent_node_id is not None:
            continue
        scope = node.scope or "body"
        if node.kind == "table":
            cells = tuple(tuple(cell.text for cell in row.cells) for row in node.obj.rows)
            items.append((scope, "table", cells, ""))
        else:
            style = node.obj.style.name if node.obj.style is not None else ""
            items.append((scope, "paragraph", node.obj.text, style))
    return items


def resolve(data: bytes, truth: list[dict[str, Any]]) -> dict[str, str]:
    """Map every logical ID in ``truth`` to its DocForge node ID in the document ``data``.

    The cells of an information block resolve too: DocForge gives each cell's paragraph a node
    of its own, whose parent is the table's node.
    """
    walk = list(walk_document(Document(BytesIO(data))))
    nodes = {(node.scope or "body", node.position_index): node
             for node in walk if node.parent_node_id is None}
    cells: dict[tuple[str, int, int], Any] = {}
    for node in walk:
        if node.parent_node_id is not None and node.row is not None:
            cells.setdefault((node.parent_node_id, node.row, node.col), node)
    resolved: dict[str, str] = {}
    for element in truth:
        locator = element["locator"]
        node = nodes.get((locator["scope"], locator["block"]))
        if node is None:
            raise GroundTruthError(f"{element['id']}: nothing at {locator}")
        _check_text(element["id"], locator, element_text(element), node_text(node))
        resolved[element["id"]] = node.node_id
        for cell in element.get("cells", ()):
            where = {**locator, **cell["cell"]}
            found = cells.get((node.node_id, cell["cell"]["row"], cell["cell"]["col"]))
            if found is None:
                raise GroundTruthError(f"{cell['id']}: no cell at {where}")
            _check_text(cell["id"], where, cell["text"], found.obj.text)
            resolved[cell["id"]] = found.node_id
    return resolved


def _check_text(element_id: str, where: dict[str, Any], expected: str, actual: str) -> None:
    if normalize_text(expected) != normalize_text(actual):
        raise GroundTruthError(
            f"{element_id} at {where}: expected {normalize_text(expected)!r}, "
            f"found {normalize_text(actual)!r}"
        )
