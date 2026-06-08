"""ORM models (spec §6).

Mapping note — fine-grained child entities from the spec are persisted as JSON
on their parent record (or as template-package files) rather than as separate
tables. This keeps the MVP schema small while losing no information:

  ExtractedElement      -> ExtractedDocument.extraction (JSON)
  DiffResult            -> AnalysisJob.diff (JSON)
  FieldDefinition       -> TemplateVersion package + AnalysisJob.field_definitions
  ValidationRule        -> TemplateVersion package + AnalysisJob.validation_rules
  PlacementInstruction  -> GenerationRequest.routing (JSON)
  ValidationReport      -> GeneratedDocument.validation (JSON)

Promoting any of these to first-class tables later is a localized change.
"""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, UUIDMixin


class Workspace(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(200), default="Default Workspace")


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), default="local")
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="owner")


class SourceDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "source_documents"
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(40), default="stored")


class ExtractedDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extracted_documents"
    source_document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.id"))
    extraction: Mapped[dict] = mapped_column(JSON)  # DocumentExtraction
    n_elements: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(40), default="extracted")


class AnalysisJob(Base, UUIDMixin, TimestampMixin):
    """A template-analysis run: ingest -> diff -> classify -> review state.

    Holds the proposed template intelligence the user reviews/edits before a
    Template is published from it.
    """

    __tablename__ = "analysis_jobs"
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")  # JobStatus
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)  # live status text
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_document_ids: Mapped[list] = mapped_column(JSON, default=list)
    representative_document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # DiffRunResult
    classification: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ClassificationResult
    field_definitions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    validation_rules: Mapped[list | None] = mapped_column(JSON, nullable=True)
    document_type_guess: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Non-fatal note when AI was configured but fell back to heuristics (e.g.
    # the document exceeded the model's context window).
    ai_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Project(Base, UUIDMixin, TimestampMixin):
    """A user-owned grouping of templates with shared, inheritable metadata.

    ``meta`` is a free-form string->string map; at generation time it pre-fills
    the fields of the project's templates (explicit per-document values win) and
    is exposed as extra Jinja variables. NB: the column is ``meta``, not
    ``metadata`` — the latter collides with SQLAlchemy's declarative MetaData.
    """

    __tablename__ = "projects"
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Template(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "templates"
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(300))
    document_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_version: Mapped[int] = mapped_column(Integer, default=0)


class TemplateVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "template_versions"
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    package_path: Mapped[str] = mapped_column(String(1000))  # folder on disk
    renderer: Mapped[str] = mapped_column(String(40), default="docxtpl")
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    n_fields: Mapped[int] = mapped_column(Integer, default=0)
    source_file_names: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)


class GenerationRequest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "generation_requests"
    template_id: Mapped[str] = mapped_column(ForeignKey("templates.id"))
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(40), default="structured_json")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    input_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    routing: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # RoutingResult
    context_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GeneratedDocument(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "generated_documents"
    generation_request_id: Mapped[str] = mapped_column(ForeignKey("generation_requests.id"))
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    template_id: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1)
    output_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ValidationReport
    status: Mapped[str] = mapped_column(String(40), default="generated")


class AIDecisionLog(Base, UUIDMixin, TimestampMixin):
    """Audit trail for AI decisions and template publication (spec §19)."""

    __tablename__ = "ai_decision_logs"
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(60))  # classify|route|section|publish
    subject_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(40), default="heuristic")  # heuristic|llm|user
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
