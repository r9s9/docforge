"""Compliance-check schemas: score a document against a template."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ComplianceDifference(BaseModel):
    kind: str  # missing_fixed | changed_fixed | missing_field | format | missing_table | table_shape
    node_id: str | None = None
    field_name: str | None = None
    severity: str = "warning"  # error | warning | info
    expected: str = ""
    found: str = ""
    message: str = ""


class DimensionScore(BaseModel):
    name: str  # structure | fields | tables
    satisfied: float = 0.0
    total: float = 0.0
    score: float = 100.0  # 0..100


class ComplianceReport(BaseModel):
    template_id: str
    version: int
    document_name: str = ""
    score: float = 100.0  # 0..100 overall
    grade: str = "pass"  # pass | warning | fail
    dimensions: list[DimensionScore] = Field(default_factory=list)
    differences: list[ComplianceDifference] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    # Ordered preview blocks of the checked document (so users see what was checked).
    document_preview: list[dict] = Field(default_factory=list)
