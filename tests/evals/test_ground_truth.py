"""Ground-truth locators resolve to the node IDs DocForge itself assigns, and a mismatch fails
loudly instead of skewing a metric."""

from __future__ import annotations

import pytest

from docforge.structure_normalizer import build_extraction
from evals.corpus.doc_types import SPECS
from evals.corpus.generator import build_document
from evals.corpus.ground_truth import GroundTruthError, normalize_text, resolve


@pytest.mark.parametrize("pair", sorted(SPECS))
@pytest.mark.parametrize("index", [0, 7])
def test_locators_match_docforge_extraction(pair, index, tmp_path):
    data, truth = build_document(SPECS[pair], index)
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
        else:
            assert normalize_text(node.text) == normalize_text(element["text"])


def test_a_wrong_text_fails_loudly():
    data, truth = build_document(SPECS["nda_en"], 0)
    truth[0] = {**truth[0], "text": "SOMETHING ELSE"}
    with pytest.raises(GroundTruthError, match="title"):
        resolve(data, truth)


def test_a_locator_that_points_nowhere_fails_loudly():
    data, truth = build_document(SPECS["nda_en"], 0)
    truth[1] = {**truth[1], "locator": {"scope": "body", "block": 999}}
    with pytest.raises(GroundTruthError, match="nothing at"):
        resolve(data, truth)
