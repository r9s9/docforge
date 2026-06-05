"""Generation status + download endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...config import Settings
from ...db.models import GeneratedDocument, GenerationRequest
from ...services.pdf import PdfError, docx_to_pdf
from ..deps import get_db, get_settings_dep
from ..serializers import generation_dto

router = APIRouter(tags=["generations"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _generated_for(db: Session, req_id: str) -> GeneratedDocument | None:
    return (
        db.query(GeneratedDocument)
        .filter_by(generation_request_id=req_id)
        .order_by(GeneratedDocument.created_at.desc())
        .first()
    )


@router.get("/generations/{req_id}")
def get_generation(req_id: str, db: Session = Depends(get_db)) -> dict:
    req = db.get(GenerationRequest, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail="generation not found")
    return generation_dto(req, _generated_for(db, req_id))


@router.get("/generations/{req_id}/download")
def download_generation(req_id: str, db: Session = Depends(get_db)) -> FileResponse:
    gen = _generated_for(db, req_id)
    if gen is None or not gen.output_path or not Path(gen.output_path).exists():
        raise HTTPException(status_code=404, detail="generated document not found")
    return FileResponse(
        gen.output_path,
        filename=gen.output_filename or "document.docx",
        media_type=DOCX_MEDIA,
    )


@router.get("/generations/{req_id}/download.pdf")
def download_generation_pdf(
    req_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> FileResponse:
    """Convert the generated DOCX to PDF (requires LibreOffice on the server)."""
    gen = _generated_for(db, req_id)
    if gen is None or not gen.output_path or not Path(gen.output_path).exists():
        raise HTTPException(status_code=404, detail="generated document not found")
    try:
        pdf_path = docx_to_pdf(gen.output_path, settings.generated_dir / "pdf")
    except PdfError as exc:
        # 501: the server can't do PDF (LibreOffice missing) — a clear, actionable error.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    name = (gen.output_filename or "document.docx").rsplit(".docx", 1)[0] + ".pdf"
    return FileResponse(pdf_path, filename=name, media_type="application/pdf")
