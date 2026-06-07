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
from ..db.models import AnalysisJob, SourceDocument
from ..schemas.classification import ClassificationResult, ElementClassification
from ..schemas.enums import ClassificationType, FieldType
from ..schemas.template import FieldDefinition
from ..storage import get_storage
from ..template_builder import build_template_docx


def _sample_value(field: FieldDefinition) -> object:
    """A readable placeholder for one field, used in the sample-filled preview."""
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
