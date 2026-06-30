"""Generation orchestration: route -> validate -> assemble -> persist (Flows 2 & 3)."""

from __future__ import annotations

import logging
from io import BytesIO

from docx import Document
from docx.table import Table
from sqlalchemy.orm import Session

from ..ai.usage import track_usage
from ..ai_router import (
    document_content,
    extraction_blocks,
    route,
    route_document_content,
)
from ..assembler import assemble
from ..common.textutil import slugify_field
from ..config import Settings, get_settings
from ..db.models import GeneratedDocument, GenerationRequest, Project, Template
from ..document_ingest import extract_source_document, store_source_document
from ..logging_setup import log_event
from ..schemas.enums import GenerationMode, JobStatus
from ..schemas.extraction import DocumentExtraction
from ..schemas.generation import GenerationInput
from ..schemas.routing import RoutingResult
from ..storage import GENERATED, get_storage, join_key
from ..structure_normalizer import iter_block_items
from ..template_registry import TemplateRegistry
from .audit import record_decision

logger = logging.getLogger("docforge.generation")

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _resolve_version(db: Session, template: Template, version: int | None) -> int:
    if version is not None:
        return version
    return template.latest_version


def _project_metadata(db: Session | None, template: Template) -> dict:
    """The assigned project's metadata, or ``{}`` (no project / no db = no-op)."""
    if db is None or not getattr(template, "project_id", None):
        return {}
    proj = db.get(Project, template.project_id)
    return dict(proj.meta or {}) if proj else {}


def _merge_with_project(base_meta: dict, context: dict) -> dict:
    """Project metadata as defaults; explicit (non-None) per-document values win.

    Keys matching a template field pre-fill that field; other keys flow through
    as extra Jinja variables (build_render_context passes unknown keys through).
    """
    merged = dict(base_meta)
    for k, v in context.items():
        if v is not None:
            merged[k] = v
    return merged


def resolve_routing(template_id, version, gen_input: GenerationInput, fields, settings) -> RoutingResult:
    """Shared routing step used by both generate and preview."""
    if gen_input.placements:
        return RoutingResult(
            template_id=template_id, version=version, placements=gen_input.placements, source="user"
        )
    if gen_input.mode == GenerationMode.UNSTRUCTURED_TEXT:
        return route(
            fields, template_id=template_id, version=version, raw_text=gen_input.raw_text, settings=settings
        )
    return route(
        fields, template_id=template_id, version=version, data=gen_input.data or {}, settings=settings
    )


def _parse_docx_blocks(data: bytes) -> list[dict]:
    """Flatten a rendered DOCX into ordered preview blocks (no file written)."""
    doc = Document(BytesIO(data))
    blocks: list[dict] = []
    for block in iter_block_items(doc):
        if isinstance(block, Table):
            rows = [[c.text.strip() for c in r.cells] for r in block.rows]
            blocks.append({"type": "table", "headers": rows[0] if rows else [], "rows": rows[1:]})
        else:  # Paragraph
            text = block.text
            if not text.strip():
                continue
            style = ""
            try:
                style = block.style.name if block.style else ""
            except Exception:
                style = ""
            kind = "heading" if style.lower().startswith(("heading", "title")) else "paragraph"
            blocks.append({"type": kind, "text": text, "style": style})
    return blocks


def route_document(
    db: Session,
    template: Template,
    *,
    filename: str,
    data: bytes,
    version: int | None = None,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
    owner_id: str | None = None,
) -> dict:
    """Extract an uploaded document's content and map it onto the template fields.

    Returns the routing result + the extracted content (for review/preview).
    """
    from ..ai_quota import increment_free_use, plan_ai_for_owner, use_ai_plan

    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = version or template.latest_version
    fields = registry.load_fields(template.id, version)

    source = store_source_document(db, filename, data, owner_id=owner_id)
    extracted = extract_source_document(db, source)
    doc = DocumentExtraction.model_validate(extracted.extraction)

    plan = plan_ai_for_owner(owner_id)

    # Prefer STRUCTURAL mapping: if the upload shares the template's structure
    # (same kind of document, incl. the original source), align it to the
    # template's representative and read each field's exact value. Only fall back
    # to fuzzy AI text-routing when structural alignment covers little (truly
    # different document).
    routing = None
    with track_usage() as usage, use_ai_plan(plan):
        rep_raw = registry.load_representative(template.id, version)
        if rep_raw:
            try:
                from ..ai_router.document import route_document_structural

                rep = DocumentExtraction.model_validate(rep_raw)
                classifications = registry.load_intelligence(template.id, version).classifications
                structural = route_document_structural(
                    rep, classifications, fields, doc, template_id=template.id, version=version
                )
                mappable = max(1, len([f for f in fields if f.field_type.value != "boolean"]))
                coverage = len(structural.placements) / mappable
                logger.info(
                    "structural document mapping covered %d/%d fields (%.0f%%)",
                    len(structural.placements), mappable, coverage * 100,
                )
                if coverage >= 0.4:  # the document clearly matches this template
                    routing = structural
            except Exception:
                logger.exception("structural document mapping failed; trying AI routing")

        if routing is None:
            content = document_content(doc)
            routing = route_document_content(fields, content, template_id=template.id, version=version)

    if plan.counts_against_free and routing.source == "llm":
        increment_free_use(owner_id)

    if routing.source == "llm":
        record_decision(
            db,
            kind="route",
            source="llm",
            subject_type="template",
            subject_id=template.id,
            model_used=routing.model_used,
            summary=f"Mapped uploaded '{filename}' into {len(routing.placements)} field(s).",
        )
    db.commit()
    return {
        "routing": routing.model_dump(mode="json"),
        "extracted": extraction_blocks(doc),
        "version": version,
        "token_usage": usage.as_dict() if usage.calls else None,
    }


def render_preview_docx(
    template: Template,
    gen_input: GenerationInput,
    *,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
    db: Session | None = None,
    owner_id: str | None = None,
) -> bytes:
    """Assemble the filled template and return the DOCX bytes (no persistence).

    Used for the live Word-page preview in the Generate UI. Callers pass
    structured data, so routing is deterministic (no LLM) and this is fast.
    """
    from ..ai_quota import plan_ai_for_owner, use_ai_plan

    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = gen_input.version or template.latest_version
    fields = registry.load_fields(template.id, version)
    template_bytes = registry.template_docx_bytes(template.id, version)
    # Previews never spend a free-tier credit (allow_free=False): own-key users
    # get full AI routing, free-tier users get the deterministic heuristic.
    with use_ai_plan(plan_ai_for_owner(owner_id, allow_free=False)):
        routing = resolve_routing(template.id, version, gen_input, fields, settings)
    context = _merge_with_project(_project_metadata(db, template), routing.to_context())
    return assemble(template_bytes, context, fields)


def preview_document(
    template: Template,
    gen_input: GenerationInput,
    *,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
    db: Session | None = None,
    owner_id: str | None = None,
) -> dict:
    """Render a template with the given input and return a structured preview
    (ordered blocks + validation) WITHOUT persisting anything."""
    from ..ai_quota import plan_ai_for_owner, use_ai_plan

    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    version = gen_input.version or template.latest_version
    fields = registry.load_fields(template.id, version)
    rules = registry.load_rules(template.id, version)
    template_bytes = registry.template_docx_bytes(template.id, version)

    # Previews never spend a free-tier credit (see render_preview_docx).
    with use_ai_plan(plan_ai_for_owner(owner_id, allow_free=False)):
        routing = resolve_routing(template.id, version, gen_input, fields, settings)
    context = _merge_with_project(_project_metadata(db, template), routing.to_context())

    from ..validator import validate

    report = None if gen_input.skip_validation else validate(context, fields, rules)
    output_bytes = assemble(template_bytes, context, fields)
    return {
        "blocks": _parse_docx_blocks(output_bytes),
        "validation": report.model_dump(mode="json") if report else None,
        "routing": routing.model_dump(mode="json"),
        "context_used": context,
    }


def generate_document(
    db: Session,
    template: Template,
    gen_input: GenerationInput,
    *,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
    owner_id: str | None = None,
) -> GeneratedDocument:
    from ..ai_quota import increment_free_use, plan_ai_for_owner, use_ai_plan

    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    settings.ensure_dirs()
    plan = plan_ai_for_owner(owner_id)

    version = _resolve_version(db, template, gen_input.version)
    fields = registry.load_fields(template.id, version)
    rules = registry.load_rules(template.id, version)
    template_bytes = registry.template_docx_bytes(template.id, version)
    log_event(
        logger, "generate.start", template=template.id, version=version,
        mode=gen_input.mode.value, ai_plan=plan.mode, fields=len(fields),
    )

    req = GenerationRequest(
        template_id=template.id,
        version=version,
        mode=gen_input.mode.value,
        status=JobStatus.RUNNING.value,
        input_payload={"data": gen_input.data, "raw_text": gen_input.raw_text},
        owner_id=owner_id,
    )
    db.add(req)
    db.flush()

    try:
        # 1) Resolve a routing result -> render context, then overlay the
        # project's inherited metadata (defaults; explicit values already win).
        # Unstructured routing may hit the model under this user's AI plan.
        with track_usage() as usage, use_ai_plan(plan):
            routing = resolve_routing(template.id, version, gen_input, fields, settings)
        context = _merge_with_project(_project_metadata(db, template), routing.to_context())
        req.routing = routing.model_dump(mode="json")
        req.token_usage = usage.as_dict() if usage.calls else None

        # 2) Validate (unless explicitly skipped).
        from ..validator import validate  # local import avoids cycle at import time

        report = None
        if not gen_input.skip_validation:
            report = validate(context, fields, rules)

        # 3) Assemble the final DOCX deterministically.
        output_bytes = assemble(template_bytes, context, fields)
        out_name = f"{slugify_field(template.name, fallback='document')}-{req.id[:8]}.docx"
        out_key = join_key(GENERATED, out_name)
        get_storage().put_bytes(out_key, output_bytes, content_type=_DOCX_CONTENT_TYPE)

        # Best-effort retention: keep generated outputs from growing without bound.
        try:
            from .retention import prune_generated

            prune_generated(settings)
        except Exception:  # never fail a generation over cleanup
            logger.debug("retention prune failed", exc_info=True)

        gen_doc = GeneratedDocument(
            generation_request_id=req.id,
            template_id=template.id,
            version=version,
            owner_id=owner_id,
            output_path=out_key,  # storage key, not a filesystem path
            output_filename=out_name,
            validation=report.model_dump(mode="json") if report else None,
            status="generated",
        )
        db.add(gen_doc)

        req.status = JobStatus.COMPLETED.value
        req.context_used = context

        if routing.source == "llm":
            record_decision(
                db,
                kind="route",
                source="llm",
                subject_type="generation",
                subject_id=req.id,
                model_used=routing.model_used,
                summary=f"Routed unstructured content into {len(routing.placements)} field(s).",
            )
    except Exception as exc:
        logger.exception("Generation failed")
        log_event(logger, "generate.failed", level=logging.ERROR, template=template.id,
                  version=version, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        req.status = JobStatus.FAILED.value
        req.error = str(exc)
        db.commit()
        raise

    log_event(
        logger, "generate.done", template=template.id, version=version,
        mode=gen_input.mode.value, routing=routing.source,
        placed=len(routing.placements), missing=len(routing.missing_required),
        validation=(report.status if report else None),
    )
    db.commit()
    db.refresh(gen_doc)
    if plan.counts_against_free and routing.source == "llm":
        increment_free_use(owner_id)
    return gen_doc
