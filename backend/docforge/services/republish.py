"""Edit a published template's fields and save a new version (no re-analysis).

Rebuilds template.docx from the *stored representative DOCX* using the edited
fields/classifications, and copies forward the package artifacts. This enables
post-publish editing + versioning without re-uploading examples.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..ai_classifier import derive_validation_rules
from ..config import Settings, get_settings
from ..db.models import Template, TemplateVersion
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, needs_field
from ..schemas.template import (
    FieldDefinition,
    ReviewSnapshot,
    TemplateIntelligence,
    TemplateManifest,
)
from ..template_builder import build_template_docx
from ..template_registry import TemplateRegistry
from .audit import record_decision


def _merge_classifications(
    prev: list[ElementClassification], fields: list[FieldDefinition]
) -> list[ElementClassification]:
    """Apply field edits onto the previous classifications.

    Fields removed by the user flip their node back to FIXED; renamed/retyped
    fields update the matching classification so the builder uses the new name.
    """
    field_by_node: dict[str, FieldDefinition] = {}
    for f in fields:
        for nid in f.node_ids:
            field_by_node[nid] = f

    out: list[ElementClassification] = []
    for c in prev:
        if needs_field(c.classification):
            f = field_by_node.get(c.node_id)
            if f is None:  # dropped by the user -> back to fixed
                c = c.model_copy(update={"classification": ClassificationType.FIXED, "field_name": None})
            else:
                c = c.model_copy(
                    update={"field_name": f.field_name, "field_type": f.field_type, "required": f.required}
                )
        out.append(c)
    return out


def republish_template(
    db: Session,
    template: Template,
    *,
    fields: list[FieldDefinition],
    classifications: list[ElementClassification] | None = None,
    document_type: str | None = None,
    notes: str = "",
    created_by: str = "local",
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> tuple[Template, TemplateVersion]:
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)

    prev = template.latest_version
    if prev < 1:
        raise ValueError("template has no published version to edit")
    if not registry.representative_docx_exists(template.id, prev):
        raise ValueError(
            "This template predates editable versions — re-create it (upload examples) to enable editing."
        )

    prev_review = registry.load_review(template.id, prev)
    prev_intel = registry.load_intelligence(template.id, prev)

    cls_list = (
        classifications
        if classifications is not None
        else _merge_classifications(prev_review.classifications, fields)
    )
    result = ClassificationResult(
        extraction_document_id="",
        classifications=cls_list,
        sections=prev_intel.sections,
        document_type_guess=document_type or prev_intel.document_type_guess,
    )
    rules = derive_validation_rules(fields)

    version = prev + 1
    # The representative DOCX lives in storage; materialize a local path for the
    # path-based builder and keep its bytes to copy into the new version package.
    with registry.representative_docx_localpath(template.id, prev) as rep_path:
        template_bytes = build_template_docx(str(rep_path), result, fields)
        rep_bytes = rep_path.read_bytes()

    intelligence = TemplateIntelligence(
        template_id=template.id,
        version=version,
        document_type_guess=result.document_type_guess,
        sections=result.sections,
        classifications=result.classifications,
        diff_summary=prev_intel.diff_summary,
        model_used_for_analysis=prev_intel.model_used_for_analysis,
        notes=notes,
    )
    manifest = TemplateManifest(
        template_id=template.id,
        version=version,
        name=template.name,
        source_file_names=registry.source_example_names(template.id, prev),
        created_at=datetime.utcnow().isoformat(),
        created_by=created_by,
        renderer="docxtpl",
        model_used_for_analysis=prev_intel.model_used_for_analysis,
        notes=notes,
    )
    review = ReviewSnapshot(
        document_type_guess=result.document_type_guess,
        classifications=result.classifications,
        field_definitions=fields,
        validation_rules=rules,
        sections=result.sections,
        edited_by_user=True,
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
        source_examples=registry.load_source_examples(template.id, prev),
        extracted_sources=registry.load_extracted_sources(template.id, prev),
        representative_extraction=registry.load_representative(template.id, prev),
        representative_docx=rep_bytes,
    )

    tv = TemplateVersion(
        template_id=template.id,
        version=version,
        package_path=package_path,
        renderer="docxtpl",
        model_used=prev_intel.model_used_for_analysis,
        n_fields=len(fields),
        source_file_names=manifest.source_file_names,
        notes=notes,
        changelog=f"Edited fields → v{version}",
    )
    db.add(tv)
    template.latest_version = version
    if document_type is not None:
        template.document_type = document_type or template.document_type

    record_decision(
        db,
        kind="publish",
        source="user",
        subject_type="template",
        subject_id=template.id,
        summary=f"Re-published '{template.name}' v{version} with {len(fields)} field(s).",
    )
    db.commit()
    db.refresh(template)
    db.refresh(tv)
    return template, tv
