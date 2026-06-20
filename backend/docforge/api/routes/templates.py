"""Template lifecycle endpoints: analyze, publish, browse, generate, route, validate."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...ai_router import route
from ...config import Settings
from ...db.models import (
    AnalysisJob,
    GeneratedDocument,
    GenerationRequest,
    Project,
    Template,
    TemplateVersion,
)
from ...document_ingest import IngestError, store_source_document
from ...jobs import submit
from ...schemas.generation import GenerationInput
from ...services import (
    generate_document,
    preview_document,
    publish_template,
    render_preview_docx,
    republish_template,
    route_document,
    run_analysis_job,
    start_analysis,
)
from ...template_registry import TemplateRegistry
from ...validator import validate
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_registry, get_settings_dep
from ..schemas import (
    PublishRequest,
    RenameRequest,
    RepublishRequest,
    RouteRequest,
    ValidateRequest,
)
from ..serializers import (
    analysis_job_dto,
    generation_dto,
    template_dto,
    version_detail_dto,
    version_dto,
)

router = APIRouter(tags=["templates"])
logger = logging.getLogger("docforge.api.templates")

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _get_template(db: Session, template_id: str, user: CurrentUser) -> Template:
    t = db.get(Template, template_id)
    # Ownership is enforced here: a template owned by someone else (or unowned /
    # "start fresh") is indistinguishable from a missing one (404, no leak).
    if t is None or t.owner_id != user.id:
        raise HTTPException(status_code=404, detail="template not found")
    return t


@router.post("/templates/analyze", status_code=202)
def analyze_templates(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Flow 1: upload 1–5 example DOCX files and start analysis.

    Returns a PENDING/RUNNING job immediately; the heavy work (which may call a
    slow local LLM) runs in the background. Poll ``GET /api/analyses/{id}``.
    """
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    if len(files) > settings.max_files_per_analysis:
        raise HTTPException(
            status_code=400,
            detail=f"at most {settings.max_files_per_analysis} files per analysis",
        )

    sources = []
    for uf in files:
        data = uf.file.read()
        try:
            sources.append(
                store_source_document(db, uf.filename or "upload.docx", data, owner_id=user.id)
            )
        except IngestError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = start_analysis(db, sources, owner_id=user.id)
    submit(run_analysis_job, job.id)
    return analysis_job_dto(job, db)


@router.post("/templates", status_code=201)
def create_template(
    req: PublishRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Flow 1 step 8: publish a reviewed analysis job into a template version."""
    job = db.get(AnalysisJob, req.analysis_job_id)
    if job is None or job.owner_id != user.id:
        raise HTTPException(status_code=404, detail="analysis job not found")
    # Validate the chosen project belongs to this user (no-leak 404).
    if req.project_id:
        proj = db.get(Project, req.project_id)
        if proj is None or proj.owner_id != user.id:
            raise HTTPException(status_code=404, detail="project not found")
    try:
        template, tv = publish_template(
            db,
            job,
            name=req.name,
            notes=req.notes,
            template_id=req.template_id,
            project_id=req.project_id,
            classifications=req.classifications,
            fields=req.fields,
            rules=req.rules,
            document_type=req.document_type,
            settings=settings,
            registry=registry,
            owner_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": template_dto(template), "version": version_dto(tv)}


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    rows = (
        db.query(Template)
        .filter(Template.owner_id == user.id)
        .order_by(Template.created_at.desc())
        .all()
    )
    return [template_dto(t) for t in rows]


@router.patch("/templates/{template_id}")
def update_template(
    template_id: str,
    req: RenameRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Edit a template's display name / document type."""
    t = _get_template(db, template_id, user)
    if req.name is not None and req.name.strip():
        t.name = req.name.strip()
    if req.document_type is not None:
        t.document_type = req.document_type.strip() or None
    db.commit()
    db.refresh(t)
    return template_dto(t)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Delete a template: its stored package, versions and generation history."""
    t = _get_template(db, template_id, user)
    registry.delete_template(template_id)
    db.query(GeneratedDocument).filter_by(template_id=template_id).delete()
    db.query(GenerationRequest).filter_by(template_id=template_id).delete()
    db.query(TemplateVersion).filter_by(template_id=template_id).delete()
    db.delete(t)
    db.commit()


@router.get("/templates/{template_id}")
def get_template(
    template_id: str,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    t = _get_template(db, template_id, user)
    # Include the assigned project (if any) so the detail view can show + pre-fill
    # the inherited metadata.
    project = db.get(Project, t.project_id) if t.project_id else None
    detail = template_dto(t, project)
    versions = (
        db.query(TemplateVersion)
        .filter_by(template_id=template_id)
        .order_by(TemplateVersion.version.desc())
        .all()
    )
    detail["versions"] = [version_dto(v) for v in versions]
    if t.latest_version:
        detail["latest"] = version_detail_dto(registry, template_id, t.latest_version)
    return detail


@router.post("/templates/{template_id}/versions", status_code=201)
def create_template_version(
    template_id: str,
    req: RepublishRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Edit fields and publish a new version of an existing template."""
    t = _get_template(db, template_id, user)
    try:
        template, tv = republish_template(
            db,
            t,
            fields=req.fields,
            classifications=req.classifications,
            document_type=req.document_type,
            notes=req.notes,
            settings=settings,
            registry=registry,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"template": template_dto(template), "version": version_dto(tv)}


@router.get("/templates/{template_id}/versions")
def list_template_versions(
    template_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    _get_template(db, template_id, user)
    rows = (
        db.query(TemplateVersion)
        .filter_by(template_id=template_id)
        .order_by(TemplateVersion.version.desc())
        .all()
    )
    return [version_dto(v) for v in rows]


@router.get("/templates/{template_id}/versions/{version}")
def get_template_version(
    template_id: str,
    version: int,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    _get_template(db, template_id, user)
    if version not in registry.list_versions(template_id):
        raise HTTPException(status_code=404, detail="version not found")
    return version_detail_dto(registry, template_id, version)


@router.get("/templates/{template_id}/versions/{version}/template.docx")
def download_template_docx(
    template_id: str,
    version: int,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    _get_template(db, template_id, user)
    if not registry.version_exists(template_id, version):
        raise HTTPException(status_code=404, detail="template file not found")
    data = registry.template_docx_bytes(template_id, version)
    return Response(content=data, media_type=DOCX_MEDIA, headers=_attachment(f"template_v{version}.docx"))


@router.get("/templates/{template_id}/versions/{version}/representative.docx")
def download_representative_docx(
    template_id: str,
    version: int,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """The original example the template was built from — the 'expected' reference
    shown as the left side of the compliance side-by-side comparison."""
    _get_template(db, template_id, user)
    if not registry.representative_docx_exists(template_id, version):
        raise HTTPException(
            status_code=404,
            detail="no stored example for this template version; re-publish to enable it",
        )
    data = registry.representative_docx_bytes(template_id, version)
    return Response(content=data, media_type=DOCX_MEDIA, headers=_attachment(f"example_v{version}.docx"))


@router.post("/templates/{template_id}/generate")
def generate(
    template_id: str,
    gen_input: GenerationInput,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Flows 2 & 3: generate a DOCX from structured data, raw text, or placements."""
    t = _get_template(db, template_id, user)
    try:
        gen = generate_document(
            db, t, gen_input, settings=settings, registry=registry, owner_id=user.id
        )
    except Exception as exc:
        logger.exception("generate failed for template %s", template_id)
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}") from exc
    req = db.get(GenerationRequest, gen.generation_request_id)
    return generation_dto(req, gen)


@router.post("/templates/{template_id}/preview")
def preview(
    template_id: str,
    gen_input: GenerationInput,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Render a preview (ordered blocks + validation) without saving a file."""
    t = _get_template(db, template_id, user)
    try:
        return preview_document(
            t, gen_input, settings=settings, registry=registry, db=db, owner_id=user.id
        )
    except Exception as exc:
        logger.exception("preview failed for template %s", template_id)
        raise HTTPException(status_code=500, detail=f"preview failed: {exc}") from exc


@router.post("/templates/{template_id}/preview.docx")
def preview_docx(
    template_id: str,
    gen_input: GenerationInput,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Return the filled template as a real DOCX, for the live Word-page preview."""
    t = _get_template(db, template_id, user)
    try:
        data = render_preview_docx(
            t, gen_input, settings=settings, registry=registry, db=db, owner_id=user.id
        )
    except Exception as exc:
        logger.exception("preview.docx failed for template %s", template_id)
        raise HTTPException(status_code=500, detail=f"preview failed: {exc}") from exc
    return Response(content=data, media_type=DOCX_MEDIA)


@router.post("/render/pdf")
def render_pdf(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Render an uploaded DOCX to PDF via LibreOffice (the "Faithful view").

    Stateless and document-agnostic: the frontend hands over whatever DOCX it is
    already previewing (template draft, generated preview, representative, or a
    compliance candidate) and gets back a pixel-faithful PDF. Returns 501 when
    LibreOffice isn't installed on the server, so the UI can fall back cleanly.
    """
    from ...logging_setup import log_event
    from ...services.pdf import PdfError, docx_bytes_to_pdf_bytes, pdf_available

    if not pdf_available():
        raise HTTPException(
            status_code=501,
            detail="Faithful (PDF) view isn't available — the server has no LibreOffice installed.",
        )
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")
    log_event(logger, "render.pdf", bytes=len(data), filename=file.filename or "preview.docx")
    try:
        pdf = docx_bytes_to_pdf_bytes(data)
    except PdfError as exc:
        log_event(logger, "render.pdf_failed", level=logging.ERROR, error=str(exc)[:200])
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=pdf, media_type="application/pdf")


@router.post("/templates/{template_id}/route-document")
def route_document_endpoint(
    template_id: str,
    file: UploadFile = File(...),
    version: int | None = None,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upload a filled DOCX; extract + map its content onto the template fields."""
    t = _get_template(db, template_id, user)
    data = file.file.read()
    try:
        return route_document(
            db, t, filename=file.filename or "document.docx", data=data,
            version=version, settings=settings, registry=registry, owner_id=user.id,
        )
    except IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("route-document failed for template %s", template_id)
        raise HTTPException(status_code=500, detail=f"document routing failed: {exc}") from exc


@router.post("/templates/{template_id}/route")
def route_content(
    template_id: str,
    req: RouteRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Flow 3 preview: route content into fields without generating."""
    t = _get_template(db, template_id, user)
    version = req.version or t.latest_version
    fields = registry.load_fields(template_id, version)
    # Routing preview: own-key users get AI; free-tier users get the heuristic
    # (no free credit spent — credits are only spent on the actual generate).
    from ...ai_quota import plan_ai_for_owner, use_ai_plan

    with use_ai_plan(plan_ai_for_owner(user.id, allow_free=False)):
        result = route(
            fields,
            template_id=template_id,
            version=version,
            raw_text=req.raw_text,
            data=req.data,
            settings=settings,
        )
    return result.model_dump(mode="json")


@router.post("/templates/{template_id}/validate")
def validate_content(
    template_id: str,
    req: ValidateRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    t = _get_template(db, template_id, user)
    version = req.version or t.latest_version
    fields = registry.load_fields(template_id, version)
    rules = registry.load_rules(template_id, version)
    report = validate(req.context, fields, rules)
    return report.model_dump(mode="json")
