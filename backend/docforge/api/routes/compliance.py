"""Compliance endpoint — score an uploaded document against a template."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...config import Settings
from ...db.models import Template
from ...document_ingest import IngestError
from ...services import check_document, fix_document
from ...template_registry import TemplateRegistry
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_registry, get_settings_dep

router = APIRouter(tags=["compliance"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
    out_name = name.rsplit(".docx", 1)[0] + "-fixed.docx"
    return Response(
        content=fixed_bytes,
        media_type=DOCX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="{out_name}"',
            "X-Fixes-Applied": str(n_fixed),
            "Access-Control-Expose-Headers": "X-Fixes-Applied",
        },
    )
