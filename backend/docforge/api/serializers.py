"""Convert ORM rows + registry artifacts into JSON-friendly response dicts."""

from __future__ import annotations

from typing import Any

from ..db.models import (
    AnalysisJob,
    ExtractedDocument,
    GeneratedDocument,
    GenerationRequest,
    Project,
    Template,
    TemplateVersion,
)
from ..template_registry import TemplateRegistry


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _elements_from_extraction(extraction: dict, classifications: list[dict]) -> list[dict[str, Any]]:
    """Top-level body elements joined with their classification (for the review UI)."""
    cls_by_node = {c["node_id"]: c for c in classifications}
    out: list[dict[str, Any]] = []
    for e in extraction.get("elements", []):
        if e.get("parent_node_id") is not None or e.get("header_footer_scope") is not None:
            continue  # body, top-level only
        c = cls_by_node.get(e["node_id"], {})
        ts = e.get("table_structure")
        out.append(
            {
                "node_id": e["node_id"],
                "type": e["type"],
                "text": (e.get("text") or "")[:400],
                "classification": c.get("classification", "FIXED"),
                "field_name": c.get("field_name"),
                "static_prefix": c.get("static_prefix"),
                "optional": c.get("optional", False),
                "headers": ts.get("headers") if ts else None,
            }
        )
    return out


def analysis_elements(db, job: AnalysisJob) -> list[dict[str, Any]]:
    """The representative document's elements + classifications, for side-by-side review."""
    if not job.representative_document_id or not job.classification:
        return []
    ed = (
        db.query(ExtractedDocument)
        .filter_by(source_document_id=job.representative_document_id)
        .order_by(ExtractedDocument.created_at.desc())
        .first()
    )
    if ed is None:
        return []
    classifications = (job.classification or {}).get("classifications", [])
    return _elements_from_extraction(ed.extraction, classifications)


def analysis_job_dto(job: AnalysisJob, db=None) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "name": job.name,
        "document_type_guess": job.document_type_guess,
        "representative_document_id": job.representative_document_id,
        "source_document_ids": job.source_document_ids,
        "model_used": job.model_used,
        "ai_warning": job.ai_warning,
        "token_usage": job.token_usage,
        "error": job.error,
        "diff_summary": (job.diff or {}).get("summary") if job.diff else None,
        "sections": (job.classification or {}).get("sections", []),
        "classifications": (job.classification or {}).get("classifications", []),
        "field_definitions": job.field_definitions or [],
        "validation_rules": job.validation_rules or [],
        "elements": analysis_elements(db, job) if db is not None else [],
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
    }


def template_dto(t: Template, project: Project | None = None) -> dict[str, Any]:
    dto = {
        "id": t.id,
        "name": t.name,
        "document_type": t.document_type,
        "description": t.description,
        "latest_version": t.latest_version,
        "project_id": t.project_id,
        "created_at": _iso(t.created_at),
        "updated_at": _iso(t.updated_at),
    }
    # The detail view passes the assigned project so the UI can prominently show
    # the inherited metadata (and pre-fill the generate form from it).
    if project is not None:
        dto["project_name"] = project.name
        dto["project_metadata"] = project.meta or {}
    return dto


def project_dto(p: Project) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "metadata": p.meta or {},
        "created_at": _iso(p.created_at),
        "updated_at": _iso(p.updated_at),
    }


def project_detail_dto(p: Project, templates: list[Template]) -> dict[str, Any]:
    return {**project_dto(p), "templates": [template_dto(t) for t in templates]}


def version_dto(tv: TemplateVersion) -> dict[str, Any]:
    return {
        "id": tv.id,
        "template_id": tv.template_id,
        "version": tv.version,
        "renderer": tv.renderer,
        "model_used": tv.model_used,
        "n_fields": tv.n_fields,
        "source_file_names": tv.source_file_names,
        "notes": tv.notes,
        "changelog": tv.changelog,
        "created_at": _iso(tv.created_at),
    }


def version_detail_dto(registry: TemplateRegistry, template_id: str, version: int) -> dict[str, Any]:
    manifest = registry.load_manifest(template_id, version)
    intelligence = registry.load_intelligence(template_id, version)
    fields = registry.load_fields(template_id, version)
    rules = registry.load_rules(template_id, version)
    return {
        "manifest": manifest.model_dump(mode="json"),
        "intelligence": intelligence.model_dump(mode="json"),
        "fields": [f.model_dump(mode="json") for f in fields],
        "rules": [r.model_dump(mode="json") for r in rules],
        "source_examples": registry.source_example_names(template_id, version),
        "elements": _template_elements(registry, template_id, version, intelligence),
    }


def _template_elements(registry, template_id, version, intelligence) -> list[dict[str, Any]]:
    """Top-level template elements + their classification — for the inspector UI."""
    rep = registry.load_representative(template_id, version)
    if not rep:
        return []
    cls_by_node = {c.node_id: c for c in intelligence.classifications}
    out: list[dict[str, Any]] = []
    for e in rep.get("elements", []):
        if e.get("parent_node_id") is not None:
            continue  # top-level only (cells are owned by their table)
        c = cls_by_node.get(e["node_id"])
        ts = e.get("table_structure")
        out.append(
            {
                "node_id": e["node_id"],
                "type": e["type"],
                "text": (e.get("text") or "")[:400],
                "scope": e.get("header_footer_scope"),
                "classification": c.classification.value if c else "FIXED",
                "field_name": c.field_name if c else None,
                "static_prefix": c.static_prefix if c else None,
                "headers": ts.get("headers") if ts else None,
            }
        )
    return out


def generation_dto(req: GenerationRequest, gen_doc: GeneratedDocument | None) -> dict[str, Any]:
    return {
        "id": req.id,
        "template_id": req.template_id,
        "version": req.version,
        "mode": req.mode,
        "status": req.status,
        "error": req.error,
        "routing": req.routing,
        "context_used": req.context_used,
        "token_usage": req.token_usage,
        "validation": gen_doc.validation if gen_doc else None,
        "output_filename": gen_doc.output_filename if gen_doc else None,
        "generated_document_id": gen_doc.id if gen_doc else None,
        "download_url": f"/api/generations/{req.id}/download" if gen_doc else None,
        "created_at": _iso(req.created_at),
    }
