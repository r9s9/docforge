"""The layout check against templates DocForge's real builder makes from an information block.

The AI modes in M4 made each value of an information block its own field, kept the labels, and
left the table in place: a form. Its first row then holds a tag where the value was. The check
must accept that, and still catch a block that was turned into a loop. Builds templates in
memory with DocForge's heuristic and builder: no settings, no database, no AI.
"""

from __future__ import annotations

from docforge.ai_classifier import derive_field_definitions
from docforge.ai_classifier.heuristic import classify_heuristic
from docforge.schemas.enums import ClassificationType, FieldType
from docforge.structure_normalizer import build_extraction
from docforge.template_builder import build_template_docx
from evals.corpus.doc_types import ALL_SPECS
from evals.corpus.generator import build_document
from evals.corpus.ground_truth import resolve, skeleton
from evals.metrics.analyze import case_outcomes, template_layout


def _template(tmp_path, pair: str, *, cells_as_fields: bool, loop: bool = False):
    data, truth = build_document(ALL_SPECS[pair], 0)
    path = tmp_path / f"{pair}.docx"
    path.write_bytes(data)
    extraction = build_extraction(str(path), "d0")
    result = classify_heuristic(extraction, None)
    node_ids = resolve(data, truth)
    by_node = {c.node_id: c for c in result.classifications}
    block = next(e for e in truth if e["kind"] == "info_table")
    table = by_node[node_ids[block["id"]]]
    table.classification = ClassificationType.FIXED
    if loop:
        table.classification = ClassificationType.REPEATABLE_TABLE
        table.field_name, table.field_type = "rows", FieldType.TABLE
    for cell in block["cells"]:
        if cells_as_fields and cell["kind"] == "field":
            c = by_node[node_ids[cell["id"]]]
            c.classification = ClassificationType.DYNAMIC_TEXT
            c.field_name, c.field_type = cell["id"].split(".", 1)[1], FieldType.TEXT
    fields = derive_field_definitions(extraction, result)
    built = build_template_docx(str(path), result, fields)
    predictions = {logical: {"class": by_node[node].classification.value}
                   for logical, node in node_ids.items() if node in by_node}
    outcomes = case_outcomes(truth, predictions)
    return truth, skeleton(data), skeleton(built), outcomes, block["id"]


def test_a_form_whose_first_value_became_a_tag_keeps_its_layout(tmp_path):
    truth, source, built, outcomes, block = _template(tmp_path, "status_report_en",
                                                      cells_as_fields=True)
    assert outcomes[block]["outcome"] == "form"
    table = next(item for item in built if item[1] == "table")
    assert table[2][0][0] == "Report date" and "{{" in table[2][0][1]  # the first value: a tag
    assert [p for p in template_layout(truth, source, built, outcomes) if p.startswith(block)] == []


def test_a_frozen_block_keeps_its_layout_and_a_looped_one_loses_rows(tmp_path):
    truth, source, built, outcomes, block = _template(tmp_path, "dpia_en", cells_as_fields=False)
    assert outcomes[block]["outcome"] == "frozen"
    assert [p for p in template_layout(truth, source, built, outcomes) if p.startswith(block)] == []
    truth, source, built, outcomes, block = _template(tmp_path, "dpia_en", cells_as_fields=False,
                                                      loop=True)
    assert outcomes[block]["outcome"] == "looped"
    assert f"{block}: rows or labels lost" in template_layout(truth, source, built, outcomes)
