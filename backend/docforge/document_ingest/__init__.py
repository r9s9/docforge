"""document_ingest — accept, validate and store uploaded DOCX files."""

from __future__ import annotations

from .service import (
    IngestError,
    extract_source_document,
    store_source_document,
    validate_docx_bytes,
    validate_upload,
)

__all__ = [
    "IngestError",
    "validate_upload",
    "validate_docx_bytes",
    "store_source_document",
    "extract_source_document",
]
