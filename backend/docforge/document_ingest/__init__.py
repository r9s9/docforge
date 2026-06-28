"""document_ingest — accept, validate and store uploaded DOCX files."""

from __future__ import annotations

from .service import (
    IngestError,
    extract_source_document,
    incoming_upload_key,
    read_incoming_bytes,
    store_source_document,
    store_source_from_key,
    validate_docx_bytes,
    validate_upload,
)

__all__ = [
    "IngestError",
    "validate_upload",
    "validate_docx_bytes",
    "store_source_document",
    "store_source_from_key",
    "incoming_upload_key",
    "read_incoming_bytes",
    "extract_source_document",
]
