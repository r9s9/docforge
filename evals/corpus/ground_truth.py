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


def resolve(data: bytes, truth: list[dict[str, Any]]) -> dict[str, str]:
    """Map every logical ID in ``truth`` to its DocForge node ID in the document ``data``."""
    nodes = top_level_nodes(Document(BytesIO(data)))
    resolved: dict[str, str] = {}
    for element in truth:
        locator = element["locator"]
        node = nodes.get((locator["scope"], locator["block"]))
        if node is None:
            raise GroundTruthError(f"{element['id']}: nothing at {locator}")
        expected, actual = normalize_text(element_text(element)), normalize_text(node_text(node))
        if expected != actual:
            raise GroundTruthError(
                f"{element['id']} at {locator}: expected {expected!r}, found {actual!r}"
            )
        resolved[element["id"]] = node.node_id
    return resolved
