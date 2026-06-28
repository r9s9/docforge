"""Ingestion service: validate -> store -> extract.

Security (spec §19): file-type validation, upload size limit, zip-bomb and
path-traversal guards (delegated to DocxPackage), and no silent external calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.base import new_uuid
from ..db.models import ExtractedDocument, SourceDocument
from ..ooxml_extractor.package import DocxError, DocxPackage, UnsafeDocxError
from ..storage import UPLOADS, get_storage, join_key
from ..structure_normalizer import build_extraction

# Browser-direct uploads land here first (one folder per user); the server then
# reads, validates and re-stores them under the canonical uploads/<doc_id> key.
UPLOADS_INCOMING = join_key(UPLOADS, "incoming")

_ALLOWED_EXT = {".docx"}
# python-docx/Word MIME, plus generic types browsers sometimes send for .docx.
_ALLOWED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream",
    "application/zip",
    "",
    None,
}
_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class IngestError(Exception):
    """A rejected or invalid upload (safe to surface to the user)."""


def validate_upload(filename: str, size_bytes: int, content_type: str | None = None) -> None:
    """Cheap pre-checks before reading/storing the file."""
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise IngestError("Only .docx files are supported")
    if size_bytes <= 0:
        raise IngestError("Uploaded file is empty")
    if size_bytes > settings.max_upload_bytes:
        raise IngestError(
            f"File exceeds the {settings.max_upload_mb} MB upload limit"
        )
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise IngestError(f"Unexpected content type: {content_type}")


def validate_docx_bytes(data: bytes) -> DocxPackage:
    """Deep validation: it must be a safe OPC package with a main document part.

    Returns the parsed DocxPackage (also enforces zip-bomb/traversal guards).
    """
    settings = get_settings()
    try:
        pkg = DocxPackage.from_bytes(
            data,
            max_entries=settings.zip_max_entries,
            max_total_bytes=settings.zip_max_total_bytes,
        )
    except UnsafeDocxError as exc:
        raise IngestError(f"Rejected unsafe DOCX: {exc}") from exc
    except DocxError as exc:
        raise IngestError(f"Invalid DOCX file: {exc}") from exc
    main = pkg.main_document_name()
    if not pkg.has(main):
        raise IngestError("DOCX is missing its main document part")
    return pkg


def store_source_document(
    db: Session,
    filename: str,
    data: bytes,
    *,
    workspace_id: str | None = None,
    owner_id: str | None = None,
) -> SourceDocument:
    """Validate and persist an uploaded DOCX, returning the SourceDocument row."""
    validate_upload(filename, len(data), None)
    validate_docx_bytes(data)  # raises on bad/unsafe input

    doc_id = new_uuid()
    # stored_path holds the STORAGE KEY (not a filesystem path) — readers fetch
    # bytes / a local temp path through the storage layer.
    key = join_key(UPLOADS, f"{doc_id}.docx")
    get_storage().put_bytes(key, data, content_type=_DOCX_CONTENT_TYPE)

    rec = SourceDocument(
        id=doc_id,
        workspace_id=workspace_id,
        owner_id=owner_id,
        filename=filename,
        stored_path=key,
        size_bytes=len(data),
        content_type=_DOCX_CONTENT_TYPE,
        sha256=hashlib.sha256(data).hexdigest(),
        status="stored",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def incoming_upload_key(owner_id: str | None, filename: str) -> str:
    """A unique, per-user staging key for a browser-direct upload."""
    safe = Path(filename or "upload.docx").name.replace("/", "_").replace("\\", "_")
    if not safe.lower().endswith(".docx"):
        safe += ".docx"
    return join_key(UPLOADS_INCOMING, owner_id or "anon", new_uuid(), safe)


def store_source_from_key(
    db: Session,
    *,
    key: str,
    filename: str,
    owner_id: str | None = None,
    workspace_id: str | None = None,
) -> SourceDocument:
    """Ingest a file the browser already uploaded straight to storage.

    The key MUST sit under this user's staging prefix — this is the trust check
    that stops a client passing an arbitrary storage key (another user's upload,
    or a template artifact) to be read back. We fetch the bytes, run the same
    validation/storage as a multipart upload, then delete the staging object.
    """
    expected_prefix = join_key(UPLOADS_INCOMING, owner_id or "anon") + "/"
    if not key.startswith(expected_prefix):
        raise IngestError("Invalid upload reference")
    storage = get_storage()
    try:
        data = storage.get_bytes(key)
    except FileNotFoundError as exc:
        raise IngestError("Uploaded file not found (the upload may have failed)") from exc
    rec = store_source_document(
        db, filename, data, owner_id=owner_id, workspace_id=workspace_id
    )
    try:
        storage.delete(key)  # best-effort cleanup of the staging object
    except Exception:
        pass
    return rec


def read_incoming_bytes(key: str, *, owner_id: str | None, filename: str) -> bytes:
    """Fetch + validate bytes for an already-uploaded staging object (no DB row).

    Used by routing/compliance, which only need the bytes, not a SourceDocument.
    Enforces the same per-user prefix guard and size/type validation, then deletes
    the staging object.
    """
    expected_prefix = join_key(UPLOADS_INCOMING, owner_id or "anon") + "/"
    if not key.startswith(expected_prefix):
        raise IngestError("Invalid upload reference")
    storage = get_storage()
    try:
        data = storage.get_bytes(key)
    except FileNotFoundError as exc:
        raise IngestError("Uploaded file not found (the upload may have failed)") from exc
    validate_upload(filename, len(data), None)
    validate_docx_bytes(data)
    try:
        storage.delete(key)
    except Exception:
        pass
    return data


def extract_source_document(db: Session, source: SourceDocument) -> ExtractedDocument:
    """Run normalization on a stored source document and persist the result."""
    try:
        # build_extraction needs a real on-disk path; materialize one from storage.
        with get_storage().local_path(source.stored_path) as p:
            extraction = build_extraction(
                str(p), document_id=source.id, filename=source.filename
            )
    except Exception as exc:  # extraction is best-effort; record the failure
        source.status = "failed"
        db.commit()
        raise IngestError(f"Extraction failed for {source.filename!r}: {exc}") from exc

    rec = ExtractedDocument(
        source_document_id=source.id,
        extraction=extraction.model_dump(mode="json"),
        n_elements=len(extraction.elements),
        page_count=extraction.page_count,
        content_hash=extraction.content_hash,
        status="extracted",
    )
    db.add(rec)
    source.status = "extracted"
    db.commit()
    db.refresh(rec)
    return rec
