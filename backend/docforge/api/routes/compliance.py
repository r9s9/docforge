"""Compliance endpoint — score an uploaded document against a template."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from ...config import Settings
from ...db.base import new_uuid
from ...db.models import Template
from ...document_ingest import IngestError, read_incoming_bytes
from ...services import check_document, fix_document
from ...storage import GENERATED, get_storage, join_key
from ...template_registry import TemplateRegistry
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_registry, get_settings_dep
from ..schemas import DocRefRequest

router = APIRouter(tags=["compliance"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _fixed_name(name: str) -> str:
    return name.rsplit(".docx", 1)[0] + "-fixed.docx"


def _owned_template(db: Session, template_id: str, user: CurrentUser) -> Template:
    template = db.get(Template, template_id)
    if template is None or template.owner_id != user.id:
        raise HTTPException(status_code=404, detail="template not found")
    return template


@router.post("/templates/{template_id}/compliance")
def check_compliance_endpoint(
    template_id: str,
    file: UploadFile = File(...),
    version: int | None = None,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Upload a document and get a compliance score + differences vs the template."""
    template = _owned_template(db, template_id, user)
    data = file.file.read()
    try:
        report = check_document(
            db,
            template,
            filename=file.filename or "document.docx",
            data=data,
            version=version,
            settings=settings,
            registry=registry,
        )
    except (IngestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report.model_dump(mode="json")


@router.post("/templates/{template_id}/compliance/fix")
def fix_compliance_endpoint(
    template_id: str,
    file: UploadFile = File(...),
    version: int | None = None,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Return a corrected copy of the upload with FIXED text patched to the template.

    Dynamic field values and any extra content are preserved; only changed/missing
    boilerplate is restored. The number of fixes applied is in ``X-Fixes-Applied``.
    """
    template = _owned_template(db, template_id, user)
    data = file.file.read()
    name = file.filename or "document.docx"
    try:
        fixed_bytes, n_fixed = fix_document(
            db, template, filename=name, data=data, version=version,
            settings=settings, registry=registry,
        )
    except (IngestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _fix_response(fixed_bytes, n_fixed, _fixed_name(name), owner_id=user.id)


def _fix_response(fixed_bytes: bytes, n_fixed: int, out_name: str, *, owner_id: str) -> Response:
    """Return the corrected DOCX, offloading large ones to a signed URL.

    Small results stream inline with the fix count in ``X-Fixes-Applied``. Large
    results (which would blow a serverless body cap) are parked in storage and
    returned as JSON ``{fixed, filename, url}`` pointing at a signed download. If
    no signed URL is available (local backend), we always stream inline.
    """
    if len(fixed_bytes) > 4_000_000:
        try:
            storage = get_storage()
            key = join_key(GENERATED, "_ephemeral", owner_id or "anon", f"{new_uuid()}.docx")
            storage.put_bytes(key, fixed_bytes, content_type=DOCX_MEDIA)
            url = storage.signed_download(key, expires_in=900, filename=out_name)
            if url:
                return JSONResponse({"fixed": n_fixed, "filename": out_name, "url": url})
        except Exception:
            pass  # fall through to inline streaming
    return Response(
        content=fixed_bytes,
        media_type=DOCX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Fixes-Applied": str(n_fixed),
            "Access-Control-Expose-Headers": "X-Fixes-Applied",
        },
    )


@router.post("/templates/{template_id}/compliance-refs")
def check_compliance_refs(
    template_id: str,
    req: DocRefRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Direct-to-storage variant of the compliance check (DOCX already uploaded)."""
    template = _owned_template(db, template_id, user)
    name = req.filename or "document.docx"
    try:
        data = read_incoming_bytes(req.key, owner_id=user.id, filename=name)
        report = check_document(
            db, template, filename=name, data=data,
            version=req.version, settings=settings, registry=registry,
        )
    except (IngestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report.model_dump(mode="json")


@router.post("/templates/{template_id}/compliance/fix-refs")
def fix_compliance_refs(
    template_id: str,
    req: DocRefRequest,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Direct-to-storage variant of the in-place fix (DOCX already uploaded)."""
    template = _owned_template(db, template_id, user)
    name = req.filename or "document.docx"
    try:
        data = read_incoming_bytes(req.key, owner_id=user.id, filename=name)
        fixed_bytes, n_fixed = fix_document(
            db, template, filename=name, data=data, version=req.version,
            settings=settings, registry=registry,
        )
    except (IngestError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _fix_response(fixed_bytes, n_fixed, _fixed_name(name), owner_id=user.id)
