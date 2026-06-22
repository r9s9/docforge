"""Build a preview DOCX for an *unpublished* analysis job.

The review UI needs to show the proposed template as a real Word file before the
user publishes. We rebuild the template DOCX from the data the AnalysisJob already
holds — exactly the inputs ``publish_template`` uses — and optionally render it
"sample-filled" so variables read like a finished document (e.g. «Project Name»)
instead of raw ``{{ jinja }}`` tags.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..assembler import assemble
from ..config import Settings, get_settings
from ..db.models import AnalysisJob, SourceDocument, Template
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, FieldType
from ..schemas.template import FieldDefinition
from ..storage import get_storage
from ..template_builder import build_template_docx
from ..template_registry import TemplateRegistry


def _sample_value(field: FieldDefinition) -> object:
    """A readable placeholder for one field, used in the sample-filled preview."""
    if field.field_type == FieldType.IMAGE:
        # No sample upload -> leave the original picture in place so the preview
        # shows the real image (logos/figures) rather than a placeholder.
        return None
    if field.field_type == FieldType.TABLE:
        # One illustrative row keyed by each column's field_name.
        return [{c.field_name: f"«{c.label or c.field_name}»" for c in field.columns}]
    if field.field_type == FieldType.BOOLEAN:
        return True
    if field.classification == ClassificationType.REPEATABLE_SECTION:
        return [f"«{field.label or field.field_name}»"]
    return f"«{field.label or field.field_name}»"


def _sample_context(fields: list[FieldDefinition]) -> dict[str, object]:
    return {f.field_name: _sample_value(f) for f in fields}


def build_job_preview_docx(
    db: Session,
    job: AnalysisJob,
    *,
    mode: str = "filled",
    fields: list[FieldDefinition] | None = None,
    classifications: list[ElementClassification] | None = None,
) -> bytes:
    """Return preview DOCX bytes for an analysis job.

    ``mode="tags"`` returns the raw template (visible ``{{ field }}`` / ``{% … %}``);
    ``mode="filled"`` renders it with readable «Label» sample values so it reads like
    a real document. ``fields`` / ``classifications`` override the job's stored values
    so the preview reflects in-progress edits from the review screen.
    """
    if not job.classification or not job.representative_document_id:
        raise ValueError("analysis job is not complete enough to preview")

    result = ClassificationResult.model_validate(job.classification)
    if classifications is not None:
        result.classifications = classifications

    if fields is None:
        fields = [FieldDefinition.model_validate(x) for x in (job.field_definitions or [])]

    rep = db.get(SourceDocument, job.representative_document_id)
    if rep is None:
        raise ValueError("representative source document not found")

    # rep.stored_path is a storage key -> materialize a local path for the builder.
    with get_storage().local_path(rep.stored_path) as rep_path:
        template_bytes = build_template_docx(str(rep_path), result, fields)
    if mode == "tags":
        return template_bytes
    return assemble(template_bytes, _sample_context(fields), fields)


def build_template_edit_preview_docx(
    template: Template,
    *,
    mode: str = "filled",
    fields: list[FieldDefinition],
    classifications: list[ElementClassification] | None = None,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> bytes:
    """Preview an *already-published* template with in-progress field edits.

    Rebuilds template.docx from the version's stored representative DOCX using the
    edited ``fields`` (exactly what ``republish_template`` would save), so the
    live preview reflects renames/removals/added-or-image fields before the user
    commits a new version. ``mode="tags"`` shows raw ``{{ placeholders }}``;
    ``mode="filled"`` shows readable «Label» sample values.
    """
    # Imported lazily to avoid a circular import (republish imports nothing here,
    # but keep the dependency direction explicit and cheap).
    from .republish import _merge_classifications

    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = template.latest_version
    if version < 1 or not registry.representative_docx_exists(template.id, version):
        raise ValueError(
            "This template predates editable previews — re-create it (upload examples) to edit it."
        )

    review = registry.load_review(template.id, version)
    intel = registry.load_intelligence(template.id, version)
    cls_list = (
        classifications
        if classifications is not None
        else _merge_classifications(review.classifications, fields)
    )
    result = ClassificationResult(
        extraction_document_id="",
        classifications=cls_list,
        sections=intel.sections,
        document_type_guess=intel.document_type_guess,
    )
    with registry.representative_docx_localpath(template.id, version) as rep_path:
        template_bytes = build_template_docx(str(rep_path), result, fields)
    if mode == "tags":
        return template_bytes
    return assemble(template_bytes, _sample_context(fields), fields)
