"""Publish a reviewed AnalysisJob into a versioned Template package (Flow 1, step 8).

Accepts optional reviewed overrides (edited classifications / fields / rules) so
the user's adjustments from the review UI are what gets built and stored.
"""

from __future__ import annotations

from datetime import datetime

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
from ..storage import get_storage
from ..structure_normalizer import build_extraction
from ..template_builder import build_template_docx
from ..template_registry import TemplateRegistry
from .audit import record_decision
from .learning import record_correction


def _diff_classifications(orig: list[dict], final: list[ElementClassification]) -> list[str]:
    """Human-readable deltas between the AI's proposal and the user's final edits.

    These become few-shot guidance replayed into future analyses of the same
    document type (the learning loop). Keyed by node so renames/retypes/
    reclassifications are captured precisely.
    """
    orig_by = {c.get("node_id"): c for c in orig}
    lines: list[str] = []
    for c in final:
        o = orig_by.get(c.node_id)
        if not o:
            continue
        o_cls, n_cls = o.get("classification"), c.classification.value
        o_name, n_name = o.get("field_name"), c.field_name
        o_type = o.get("field_type")
        n_type = c.field_type.value if c.field_type else None
        label = n_name or o_name or (o.get("static_prefix") or "").strip(": ") or "an element"
        if o_cls != n_cls:
            lines.append(f'reclassified "{label}" from {o_cls} to {n_cls}')
        elif o_name and n_name and o_name != n_name:
            lines.append(f'renamed field "{o_name}" to "{n_name}"')
        elif n_name and o_type != n_type and n_type:
            lines.append(f'set field "{n_name}" type to {n_type} (was {o_type})')
    return lines


def _capture_learning(db, job, final: list[ElementClassification], document_type, owner_id) -> None:
    """Record how the user corrected the AI's classification (best-effort)."""
    if not owner_id:
        return
    orig = (job.classification or {}).get("classifications", [])
    if not orig:
        return
    summaries = _diff_classifications(orig, final)
    if summaries:
        record_correction(
            db, owner_id=owner_id, document_type=document_type,
            kind="classify", summaries=summaries[:20],
        )


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
    project_id: str | None = None,
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
            project_id=project_id,
        )
        db.add(template)
        db.flush()
        version = 1

    # Build the template DOCX from the representative example, and capture its
    # normalized extraction (used by compliance checks + the element inspector).
    # rep.stored_path is a storage key -> materialize a local path for the
    # path-based builders, and keep the bytes to store in the package.
    storage = get_storage()
    with storage.local_path(rep.stored_path) as rep_path:
        rep_bytes = rep_path.read_bytes()
        template_bytes = build_template_docx(str(rep_path), result, fields)
        rep_extraction = build_extraction(str(rep_path), rep.id, rep.filename).model_dump(mode="json")

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
        if sd and storage.exists(sd.stored_path):
            source_examples[sd.filename] = storage.get_bytes(sd.stored_path)
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
        representative_docx=rep_bytes,
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

    # Learning loop: when the user edited the AI's proposal, remember the deltas
    # so future analyses of this document type adapt to their conventions.
    if edited:
        _capture_learning(db, job, result.classifications, result.document_type_guess, owner_id)

    db.commit()
    db.refresh(template)
    db.refresh(tv)
    return template, tv
