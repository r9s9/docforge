"""Compliance endpoint — score an uploaded document against a template."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...config import Settings
from ...db.models import Template
from ...document_ingest import IngestError
from ...services import check_document
from ...template_registry import TemplateRegistry
from ..deps import get_db, get_registry, get_settings_dep

router = APIRouter(tags=["compliance"])


@router.post("/templates/{template_id}/compliance")
def check_compliance_endpoint(
    template_id: str,
    file: UploadFile = File(...),
    version: int | None = None,
    db: Session = Depends(get_db),
    registry: TemplateRegistry = Depends(get_registry),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    """Upload a document and get a compliance score + differences vs the template."""
    template = db.get(Template, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template not found")
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
