"""Request/response DTOs for the HTTP API (thin wrappers over domain schemas)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..schemas.classification import ElementClassification
from ..schemas.template import FieldDefinition, ValidationRule


class PublishRequest(BaseModel):
    """Create/publish a template version from a reviewed analysis job."""

    analysis_job_id: str
    name: str | None = None
    document_type: str | None = None
    notes: str = ""
    template_id: str | None = None  # set to publish a new version of an existing template
    # Reviewed overrides from the UI (omit to use the analysis defaults).
    classifications: list[ElementClassification] | None = None
    fields: list[FieldDefinition] | None = None
    rules: list[ValidationRule] | None = None


class RenameRequest(BaseModel):
    """Edit a template's display name / document type."""

    name: str | None = None
    document_type: str | None = None


class RepublishRequest(BaseModel):
    """Edit fields and publish a new template version (no re-analysis)."""

    fields: list[FieldDefinition]
    classifications: list[ElementClassification] | None = None
    document_type: str | None = None
    notes: str = ""


class RouteRequest(BaseModel):
    version: int | None = None
    raw_text: str | None = None
    data: dict[str, Any] | None = None


class ValidateRequest(BaseModel):
    version: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)
