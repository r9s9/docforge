"""Unit tests for direct-to-storage uploads (Vercel 4.5 MB body-cap bypass)."""

from __future__ import annotations

import pytest

from docforge.document_ingest import (
    IngestError,
    incoming_upload_key,
    read_incoming_bytes,
    store_source_from_key,
)
from docforge.storage import get_storage
from docforge.storage.local import LocalStorage


def test_signed_urls_default_to_none(tmp_path):
    """The local backend can't issue signed URLs → callers must fall back."""
    st = LocalStorage(tmp_path)
    assert st.signed_upload("uploads/x.docx") is None
    assert st.signed_download("uploads/x.docx") is None


def test_incoming_upload_key_is_scoped_and_docx():
    key = incoming_upload_key("user-123", "Report")  # no extension
    assert key.startswith("uploads/incoming/user-123/")
    assert key.endswith(".docx")


def test_incoming_upload_key_strips_path_separators():
    key = incoming_upload_key("u", "../../etc/passwd.docx")
    # The filename segment must not let a key escape the staging folder.
    assert ".." not in key.split("/")
    assert key.startswith("uploads/incoming/u/")


def test_read_incoming_bytes_rejects_foreign_key(settings_tmp):
    # A key outside the caller's staging prefix must be refused (no cross-user read).
    with pytest.raises(IngestError):
        read_incoming_bytes(
            "uploads/incoming/someone-else/abc/file.docx", owner_id="me", filename="file.docx"
        )
    with pytest.raises(IngestError):
        read_incoming_bytes(
            "templates/t1/1/template.docx", owner_id="me", filename="template.docx"
        )


def test_store_source_from_key_roundtrip(db_session, settings_tmp, project_docs):
    data = project_docs[0].read_bytes()
    owner = "owner-xyz"
    key = incoming_upload_key(owner, "report.docx")
    get_storage().put_bytes(key, data)

    source = store_source_from_key(db_session, key=key, filename="report.docx", owner_id=owner)
    assert source.id
    assert source.owner_id == owner
    assert source.sha256
    # The canonical copy exists and the staging object was cleaned up.
    assert (settings_tmp.uploads_dir / f"{source.id}.docx").exists()
    assert not get_storage().exists(key)


def test_store_source_from_key_guards_owner(db_session, settings_tmp, project_docs):
    data = project_docs[0].read_bytes()
    key = incoming_upload_key("real-owner", "report.docx")
    get_storage().put_bytes(key, data)
    # A different owner must not be able to ingest someone else's staged upload.
    with pytest.raises(IngestError):
        store_source_from_key(db_session, key=key, filename="report.docx", owner_id="attacker")
