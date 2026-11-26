"""Ground-truth locators resolve to the node IDs DocForge itself assigns, and a mismatch fails
loudly instead of skewing a metric."""

from __future__ import annotations

import pytest

from docforge.structure_normalizer import build_extraction
from evals.corpus.doc_types import ALL_SPECS, SPECS
from evals.corpus.generator import build_document
from evals.corpus.ground_truth import GroundTruthError, normalize_text, resolve


@pytest.mark.parametrize("pair", sorted(ALL_SPECS))
@pytest.mark.parametrize("index", [0, 7])
def test_locators_match_docforge_extraction(pair, index, tmp_path):
    data, truth = build_document(ALL_SPECS[pair], index)
    node_ids = resolve(data, truth)
    path = tmp_path / "doc.docx"
    path.write_bytes(data)
    extraction = build_extraction(str(path), document_id="t", filename="doc.docx")
    by_node = {element.node_id: element for element in extraction.elements}
    for element in truth:
        node = by_node[node_ids[element["id"]]]
        assert node.parent_node_id is None
        if element["kind"] == "table":
            assert node.table_structure.headers == element["headers"]
        elif element["kind"] == "info_table":
            assert node.table_structure.rows == element["rows"]
            for cell in element["cells"]:  # each cell is a node inside the table
                inner = by_node[node_ids[cell["id"]]]
                assert inner.parent_node_id == node.node_id
                assert normalize_text(inner.text) == normalize_text(cell["text"])
        else:
            assert normalize_text(node.text) == normalize_text(element["text"])


def test_a_wrong_text_fails_loudly():
    data, truth = build_document(SPECS["nda_en"], 0)
    truth[0] = {**truth[0], "text": "SOMETHING ELSE"}
    with pytest.raises(GroundTruthError, match="title"):
        resolve(data, truth)


def _with_cell(truth, cell_index, **changes):
    block = next(i for i, e in enumerate(truth) if e["kind"] == "info_table")
    cells = [dict(c) for c in truth[block]["cells"]]
    cells[cell_index].update(changes)
    return [*truth[:block], {**truth[block], "cells": cells}, *truth[block + 1:]]


def test_a_wrong_cell_text_or_a_missing_cell_fails_loudly():
    data, truth = build_document(ALL_SPECS["dpia_en"], 0)
    with pytest.raises(GroundTruthError, match="cell.reference"):
        resolve(data, _with_cell(truth, 3, text="DPIA-1999-000"))
    with pytest.raises(GroundTruthError, match="no cell at"):
        resolve(data, _with_cell(truth, 3, cell={"row": 9, "col": 1}))


def test_a_locator_that_points_nowhere_fails_loudly():
    data, truth = build_document(SPECS["nda_en"], 0)
    truth[1] = {**truth[1], "locator": {"scope": "body", "block": 999}}
    with pytest.raises(GroundTruthError, match="nothing at"):
        resolve(data, truth)
