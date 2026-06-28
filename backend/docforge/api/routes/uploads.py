"""Direct-to-storage upload signing.

The browser asks for a short-lived signed URL, PUTs the file straight into object
storage, then calls an ``*-refs`` endpoint with the returned storage key. This
keeps file bytes off the API request path — required on hosts that cap request
bodies (Vercel: 4.5 MB) and faster everywhere.

When the active storage backend can't issue signed URLs (the local filesystem,
used in dev/tests), this returns ``{"direct": false}`` and the client falls back
to a normal multipart upload.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...document_ingest import incoming_upload_key
from ...storage import get_storage
from ..auth import CurrentUser, get_current_user
from ..deps import get_settings_dep
from ..schemas import SignUploadRequest

router = APIRouter(tags=["uploads"])

_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.post("/uploads/sign")
def sign_upload(
    req: SignUploadRequest,
    settings=Depends(get_settings_dep),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """Return a direct-upload target for one .docx, or signal multipart fallback."""
    if Path(req.filename or "").suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="Only .docx files are supported")

    key = incoming_upload_key(user.id, req.filename)
    storage = get_storage()
    try:
        target = storage.signed_upload(key, content_type=_DOCX_CONTENT_TYPE)
    except Exception as exc:  # storage misconfigured — let the client fall back
        raise HTTPException(status_code=502, detail=f"could not sign upload: {exc}") from exc
    if not target:
        # Local backend: no signed URLs — client should send multipart instead.
        return {"direct": False}
    return {"direct": True, "key": key, **target}
