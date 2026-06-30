"""Phase-1 analysis agent: self-critique corrections + learning capture."""

from __future__ import annotations

from docforge.ai.prompts import (
    LLMClassifyResponse,
    LLMCritiqueResponse,
    LLMElementClassification,
    LLMUnderstanding,
)
from docforge.ai_classifier.llm import classify_llm
from docforge.schemas.classification import ElementClassification
from docforge.schemas.enums import ClassificationType, FieldType
from docforge.services.publish import _diff_classifications
from docforge.structure_normalizer import build_extraction


def test_self_critique_applies_corrections(project_docs):
    """The critique pass can flip a wrong FIXED label into the right DYNAMIC field."""
    ext = build_extraction(project_docs[0], "d0")
    nid = ext.top_level_elements()[1].node_id

    class _CritiqueClient:
        model = "mock"
        active = True
        provider = "openai"
        supports_streaming = False

        def complete_agentic(self, *, schema, **kw):
            if schema is LLMUnderstanding:
                return LLMUnderstanding()
            if schema is LLMCritiqueResponse:
                return LLMCritiqueResponse(
                    corrections=[
                        LLMElementClassification(
                            node_id=nid, classification="DYNAMIC_DATE", field_name="invoice_date",
                            field_type="date", description="Invoice date", confidence=0.95,
                        )
                    ]
                )
            # classify pass: low-confidence FIXED -> flagged as questionable
            return LLMClassifyResponse(
                classifications=[
                    LLMElementClassification(node_id=nid, classification="FIXED", confidence=0.3)
                ]
            )

        def for_tier(self, tier):
            return self

    result = classify_llm(ext, None, _CritiqueClient())
    c = next(c for c in result.classifications if c.node_id == nid)
    assert c.classification is ClassificationType.DYNAMIC_DATE
    assert c.field_name == "invoice_date"
    assert c.field_type is FieldType.DATE
    assert "[critique]" in c.rationale


def test_learning_diff_captures_reclassify_and_rename():
    orig = [
        {"node_id": "a", "classification": "FIXED", "field_name": None, "field_type": None},
        {"node_id": "b", "classification": "DYNAMIC_TEXT", "field_name": "name", "field_type": "text"},
        {"node_id": "c", "classification": "DYNAMIC_TEXT", "field_name": "amt", "field_type": "text"},
    ]
    final = [
        ElementClassification(
            node_id="a", classification=ClassificationType.DYNAMIC_NUMBER,
            field_name="amount", field_type=FieldType.NUMBER,
        ),
        ElementClassification(
            node_id="b", classification=ClassificationType.DYNAMIC_TEXT,
            field_name="full_name", field_type=FieldType.TEXT,
        ),
        ElementClassification(
            node_id="c", classification=ClassificationType.DYNAMIC_NUMBER,
            field_name="amt", field_type=FieldType.NUMBER,
        ),
    ]
    lines = _diff_classifications(orig, final)
    assert any("reclassified" in s and "FIXED" in s for s in lines)  # a
    assert any('renamed field "name" to "full_name"' in s for s in lines)  # b
    assert any("reclassified" in s for s in lines)  # c (text->number)


def test_learning_diff_empty_when_unchanged():
    orig = [{"node_id": "a", "classification": "FIXED", "field_name": None, "field_type": None}]
    final = [ElementClassification(node_id="a", classification=ClassificationType.FIXED)]
    assert _diff_classifications(orig, final) == []
