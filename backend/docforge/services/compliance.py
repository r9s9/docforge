"""Compliance orchestration: ingest a candidate doc, score it vs a template."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai_router import extraction_blocks
from ..compliance import check_compliance
from ..config import Settings, get_settings
from ..db.models import Template
from ..document_ingest import extract_source_document, store_source_document
from ..schemas.compliance import ComplianceReport
from ..schemas.extraction import DocumentExtraction
from ..template_registry import TemplateRegistry
from .audit import record_decision


def check_document(
    db: Session,
    template: Template,
    *,
    filename: str,
    data: bytes,
    version: int | None = None,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> ComplianceReport:
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = version or template.latest_version

    rep_raw = registry.load_representative(template.id, version)
    if rep_raw is None:
        raise ValueError(
            "This template version has no stored representative structure; "
            "re-publish the template to enable compliance checks."
        )
    rep = DocumentExtraction.model_validate(rep_raw)
    intelligence = registry.load_intelligence(template.id, version)
    fields = registry.load_fields(template.id, version)
    rules = registry.load_rules(template.id, version)

    # Persist + extract the candidate document (also gives an audit trail).
    source = store_source_document(db, filename, data)
    extracted = extract_source_document(db, source)
    doc = DocumentExtraction.model_validate(extracted.extraction)

    report = check_compliance(
        rep,
        intelligence.classifications,
        fields,
        rules,
        doc,
        template_id=template.id,
        version=version,
        document_name=filename,
    )
    report.document_preview = extraction_blocks(doc)

    record_decision(
        db,
        kind="compliance",
        source="heuristic",
        subject_type="template",
        subject_id=template.id,
        summary=f"Compliance check of '{filename}': {report.score} ({report.grade}).",
    )
    db.commit()
    return report
