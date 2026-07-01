"""Unit tests for the heuristic classifier + field/rule derivation."""

from __future__ import annotations

from docforge.ai_classifier import (
    classify,
    derive_field_definitions,
    derive_validation_rules,
)
from docforge.multi_doc_differ import diff_documents
from docforge.schemas.classification import ClassificationResult, ElementClassification
from docforge.schemas.enums import ClassificationType, FieldType
from docforge.structure_normalizer import build_extraction


def _analyze(docs):
    exts = [build_extraction(p, f"d{i}") for i, p in enumerate(docs)]
    diff = diff_documents(exts) if len(exts) >= 2 else None
    result = classify(exts[0], diff)
    fields = derive_field_definitions(exts[0], result)
    return exts, result, fields


def test_classify_project_field_types(project_docs):
    _, result, fields = _analyze(project_docs)
    by_name = {f.field_name: f for f in fields}
    assert by_name["project_name"].field_type == FieldType.TEXT  # not person
    assert by_name["report_date"].field_type == FieldType.DATE
    assert by_name["prepared_by"].field_type == FieldType.PERSON


def test_classify_detects_repeatable_table_with_typed_columns(project_docs):
    _, _, fields = _analyze(project_docs)
    tables = [f for f in fields if f.field_type == FieldType.TABLE]
    assert tables
    table = tables[0]
    assert table.classification == ClassificationType.REPEATABLE_TABLE
    col_types = {c.field_name: c.field_type for c in table.columns}
    assert col_types["due_date"] == FieldType.DATE


def test_classify_doc_type_guess(project_docs):
    _, result, _ = _analyze(project_docs)
    assert "Project" in result.document_type_guess


def test_validation_rules_generated(project_docs):
    _, _, fields = _analyze(project_docs)
    rules = derive_validation_rules(fields)
    rule_types = {r.rule_type.value for r in rules}
    assert "required" in rule_types
    assert "date_format" in rule_types
    assert "table_schema" in rule_types


def test_classify_single_document_still_finds_fields(project_docs):
    ext = build_extraction(project_docs[0], "solo")
    result = classify(ext, None)  # no diff evidence
    fields = derive_field_definitions(ext, result)
    names = {f.field_name for f in fields}
    # labeled values become dynamic even without diff evidence
    assert "project_name" in names
    assert len(fields) >= 3


def test_derive_field_definitions_fills_blank_description(project_docs):
    # The heuristic classifier (and sometimes the LLM) leaves description empty.
    # Routing/compose lean on description as their main semantic signal beyond
    # the bare field name, so a blank one must never reach the field definition.
    ext = build_extraction(project_docs[0], "solo")
    node_id = ext.top_level_elements()[1].node_id
    result = ClassificationResult(
        extraction_document_id=ext.document_id,
        classifications=[
            ElementClassification(
                node_id=node_id,
                classification=ClassificationType.DYNAMIC_DATE,
                field_name="issued_on",
                field_type=FieldType.DATE,
                description="",  # blank on purpose
                static_prefix="Issued On: ",
                confidence=0.8,
            )
        ],
    )
    fields = derive_field_definitions(ext, result)
    f = next(f for f in fields if f.field_name == "issued_on")
    assert f.description.strip() != ""
    assert "Issued On" in f.description  # carries the document's own label forward
