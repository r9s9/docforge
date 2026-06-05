"""Unit tests for the ingestion service (validation + storage + extraction)."""

from __future__ import annotations

import pytest

from docforge.document_ingest import (
    IngestError,
    extract_source_document,
    store_source_document,
    validate_upload,
)


def test_validate_upload_rejects_non_docx():
    with pytest.raises(IngestError):
        validate_upload("notes.txt", 1000)


def test_validate_upload_rejects_empty():
    with pytest.raises(IngestError):
        validate_upload("a.docx", 0)


def test_store_rejects_non_docx_bytes(db_session, settings_tmp):
    with pytest.raises(IngestError):
        store_source_document(db_session, "fake.docx", b"this is not a zip")


def test_store_and_extract_roundtrip(db_session, settings_tmp, project_docs):
    data = project_docs[0].read_bytes()
    source = store_source_document(db_session, "project_report_1.docx", data)
    assert source.id
    assert source.status == "extracted" or source.status == "stored"
    assert source.sha256

    extracted = extract_source_document(db_session, source)
    assert extracted.n_elements > 5
    assert extracted.extraction["filename"] == "project_report_1.docx"
    # stored file exists under the isolated temp data dir
    assert (settings_tmp.uploads_dir / f"{source.id}.docx").exists()
