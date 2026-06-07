"""Generation status + download endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...config import Settings
from ...db.models import GeneratedDocument, GenerationRequest
from ...services.pdf import PdfError, docx_to_pdf
from ...storage import get_storage
from ..auth import CurrentUser, get_current_user
from ..deps import get_db, get_settings_dep
from ..serializers import generation_dto

router = APIRouter(tags=["generations"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _generated_for(db: Session, req_id: str) -> GeneratedDocument | None:
    return (
        db.query(GeneratedDocument)
        .filter_by(generation_request_id=req_id)
        .order_by(GeneratedDocument.created_at.desc())
        .first()
    )


def _get_request(db: Session, req_id: str, user: CurrentUser) -> GenerationRequest:
    req = db.get(GenerationRequest, req_id)
    if req is None or req.owner_id != user.id:
        raise HTTPException(status_code=404, detail="generation not found")
    return req


@router.get("/generations/{req_id}")
def get_generation(
    req_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    req = _get_request(db, req_id, user)
    return generation_dto(req, _generated_for(db, req_id))


@router.get("/generations/{req_id}/download")
def download_generation(
    req_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    _get_request(db, req_id, user)
    gen = _generated_for(db, req_id)
    storage = get_storage()
    if gen is None or not gen.output_path or not storage.exists(gen.output_path):
        raise HTTPException(status_code=404, detail="generated document not found")
    return Response(
        content=storage.get_bytes(gen.output_path),
        media_type=DOCX_MEDIA,
        headers=_attachment(gen.output_filename or "document.docx"),
    )


@router.get("/generations/{req_id}/download.pdf")
def download_generation_pdf(
    req_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    """Convert the generated DOCX to PDF (requires LibreOffice on the server)."""
    _get_request(db, req_id, user)
    gen = _generated_for(db, req_id)
    storage = get_storage()
    if gen is None or not gen.output_path or not storage.exists(gen.output_path):
        raise HTTPException(status_code=404, detail="generated document not found")
    name = (gen.output_filename or "document.docx").rsplit(".docx", 1)[0] + ".pdf"
    # LibreOffice needs real files: materialize the source DOCX and a temp out dir.
    try:
        with storage.local_path(gen.output_path) as docx_path:
            out_dir = Path(tempfile.mkdtemp(prefix="docforge-pdf-"))
            try:
                pdf_path = docx_to_pdf(docx_path, out_dir)
                pdf_bytes = pdf_path.read_bytes()
            finally:
                import shutil as _shutil

                _shutil.rmtree(out_dir, ignore_errors=True)
    except PdfError as exc:
        # 501: the server can't do PDF (LibreOffice missing) — a clear, actionable error.
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return Response(
        content=pdf_bytes, media_type="application/pdf", headers=_attachment(name)
    )
