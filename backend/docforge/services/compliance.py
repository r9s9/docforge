"""Compliance orchestration: ingest a candidate doc, score it vs a template."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..ai.client import LLMClient
from ..ai.usage import track_usage
from ..ai_quota import increment_free_use, plan_ai_for_owner, use_ai_plan
from ..ai_router import extraction_blocks
from ..compliance import check_compliance
from ..compliance.judge import judge_compliance
from ..config import Settings, get_settings
from ..db.models import ComplianceRun, Template
from ..document_ingest import extract_source_document, store_source_document
from ..schemas.compliance import ComplianceReport
from ..schemas.extraction import DocumentExtraction
from ..settings_store import generation_ai_config
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
    owner_id: str | None = None,
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
    source = store_source_document(db, filename, data, owner_id=owner_id)
    extracted = extract_source_document(db, source)
    doc = DocumentExtraction.model_validate(extracted.extraction)

    # Deterministic backbone: structural alignment + 3-dimension score.
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

    # AI semantic judge: classify each difference material vs benign (best-effort,
    # under this user's AI plan). The deterministic score/grade is preserved.
    doc_type = template.document_type or intelligence.document_type_guess or ""
    plan = plan_ai_for_owner(owner_id)
    with track_usage() as usage, use_ai_plan(plan):
        client = LLMClient(generation_ai_config())
        if client.active:
            judge_compliance(report, document_type=doc_type, client=client)
    if usage.calls:
        report.token_usage = usage.as_dict()
        if plan.counts_against_free:
            increment_free_use(owner_id)

    run = ComplianceRun(
        owner_id=owner_id,
        template_id=template.id,
        version=version,
        document_name=filename,
        score=int(report.score),
        grade=report.grade,
        report=report.model_dump(mode="json"),
        token_usage=usage.as_dict() if usage.calls else None,
    )
    db.add(run)

    record_decision(
        db,
        kind="compliance",
        source="llm" if usage.calls else "heuristic",
        subject_type="template",
        subject_id=template.id,
        owner_id=owner_id,
        summary=f"Compliance check of '{filename}': {report.score} ({report.grade}).",
    )
    db.commit()
    return report
