"""Publish a reviewed AnalysisJob into a versioned Template package (Flow 1, step 8).

Accepts optional reviewed overrides (edited classifications / fields / rules) so
the user's adjustments from the review UI are what gets built and stored.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import AnalysisJob, ExtractedDocument, SourceDocument, Template, TemplateVersion
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.template import (
    FieldDefinition,
    ReviewSnapshot,
    TemplateIntelligence,
    TemplateManifest,
    ValidationRule,
)
from ..structure_normalizer import build_extraction
from ..template_builder import build_template_docx
from ..template_registry import TemplateRegistry
from .audit import record_decision


def publish_template(
    db: Session,
    job: AnalysisJob,
    *,
    name: str | None = None,
    created_by: str = "local",
    notes: str = "",
    template_id: str | None = None,
    classifications: list[ElementClassification] | None = None,
    fields: list[FieldDefinition] | None = None,
    rules: list[ValidationRule] | None = None,
    document_type: str | None = None,
    workspace_id: str | None = None,
    owner_id: str | None = None,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> tuple[Template, TemplateVersion]:
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)

    if not job.classification or not job.representative_document_id:
        raise ValueError("AnalysisJob is not complete enough to publish")

    # Reconstruct the classification, applying any reviewed overrides.
    result = ClassificationResult.model_validate(job.classification)
    edited = any(x is not None for x in (classifications, fields, rules, document_type))
    if classifications is not None:
        result.classifications = classifications
    if document_type is not None:
        result.document_type_guess = document_type

    if fields is None:
        fields = [FieldDefinition.model_validate(x) for x in (job.field_definitions or [])]
    if rules is None:
        rules = [ValidationRule.model_validate(x) for x in (job.validation_rules or [])]

    rep = db.get(SourceDocument, job.representative_document_id)
    if rep is None:
        raise ValueError("representative source document not found")

    # Create (or version) the Template record so we know the id/version.
    if template_id:
        template = db.get(Template, template_id)
        if template is None:
            raise ValueError("template_id not found")
        version = template.latest_version + 1
    else:
        template = Template(
            name=name or result.document_type_guess or "Untitled Template",
            document_type=result.document_type_guess,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        db.add(template)
        db.flush()
        version = 1

    # Build the template DOCX from the representative example, and capture its
    # normalized extraction (used by compliance checks + the element inspector).
    template_bytes = build_template_docx(rep.stored_path, result, fields)
    rep_extraction = build_extraction(rep.stored_path, rep.id, rep.filename).model_dump(mode="json")

    # Assemble package artifacts.
    intelligence = TemplateIntelligence(
        template_id=template.id,
        version=version,
        document_type_guess=result.document_type_guess,
        sections=result.sections,
        classifications=result.classifications,
        diff_summary=(job.diff or {}).get("summary") if job.diff else None,
        model_used_for_analysis=job.model_used,
        notes=notes,
    )

    source_examples: dict[str, bytes] = {}
    source_file_names: list[str] = []
    for sid in job.source_document_ids or []:
        sd = db.get(SourceDocument, sid)
        if sd and Path(sd.stored_path).exists():
            source_examples[sd.filename] = Path(sd.stored_path).read_bytes()
            source_file_names.append(sd.filename)

    extracted_sources: dict[str, dict] = {}
    for ed in (
        db.query(ExtractedDocument)
        .filter(ExtractedDocument.source_document_id.in_(job.source_document_ids or []))
        .all()
    ):
        fname = ed.extraction.get("filename", ed.id)
        extracted_sources[fname] = ed.extraction

    manifest = TemplateManifest(
        template_id=template.id,
        version=version,
        name=template.name,
        source_file_names=source_file_names,
        created_at=datetime.utcnow().isoformat(),
        created_by=created_by,
        renderer="docxtpl",
        model_used_for_analysis=job.model_used,
        notes=notes,
    )
    review = ReviewSnapshot(
        document_type_guess=result.document_type_guess,
        classifications=result.classifications,
        field_definitions=fields,
        validation_rules=rules,
        sections=result.sections,
        edited_by_user=edited,
    )

    package_path = registry.save_version(
        template.id,
        version,
        template_docx=template_bytes,
        intelligence=intelligence,
        fields=fields,
        rules=rules,
        manifest=manifest,
        review=review,
        source_examples=source_examples,
        extracted_sources=extracted_sources,
        representative_extraction=rep_extraction,
        representative_docx=Path(rep.stored_path).read_bytes(),
    )

    tv = TemplateVersion(
        template_id=template.id,
        version=version,
        package_path=str(package_path),
        renderer="docxtpl",
        model_used=job.model_used,
        n_fields=len(fields),
        source_file_names=source_file_names,
        notes=notes,
        changelog=("Initial version" if version == 1 else f"Version {version}"),
    )
    db.add(tv)
    template.latest_version = version

    record_decision(
        db,
        kind="publish",
        source="user" if edited else result.source,
        subject_type="template",
        subject_id=template.id,
        model_used=job.model_used,
        summary=f"Published '{template.name}' v{version} with {len(fields)} field(s).",
        workspace_id=workspace_id,
    )

    db.commit()
    db.refresh(template)
    db.refresh(tv)
    return template, tv
