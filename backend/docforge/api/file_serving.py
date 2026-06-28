"""Helpers for returning DOCX bytes without tripping serverless body limits.

Some hosts cap a function's request/response body (Vercel: 4.5 MB). To stay
under that, file responses prefer a redirect to a short-lived signed storage URL
so the browser fetches the bytes straight from object storage. When the backend
can't issue a signed URL (the local filesystem backend, used in dev/tests) we
stream the bytes through the API as before — there is no body cap there.

The browser side is unaffected: ``fetch`` follows redirects transparently, and
on a cross-origin redirect it drops the Authorization header (so the API Bearer
token never leaks to storage; the signed URL's own token authorizes the read).
"""

from __future__ import annotations

from fastapi.responses import RedirectResponse, Response

from ..db.base import new_uuid
from ..storage import GENERATED, Storage, get_storage, join_key

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# Responses larger than this are offloaded to a signed URL when possible. Picked
# safely below Vercel's 4.5 MB cap; smaller payloads stream inline (one hop,
# no extra storage round-trip).
_INLINE_MAX_BYTES = 4_000_000

# Where on-the-fly generated previews/fixes are parked so they can be served via
# a signed URL. Under GENERATED so normal retention pruning sweeps them up.
_EPHEMERAL_PREFIX = join_key(GENERATED, "_ephemeral")


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def stored_file_response(
    key: str,
    *,
    filename: str | None = None,
    storage: Storage | None = None,
) -> Response:
    """Serve an already-stored object: redirect to a signed URL, else stream.

    ``filename`` set => download with that name (Content-Disposition); unset =>
    inline (used by the in-browser DOCX preview renderer).
    """
    storage = storage or get_storage()
    url = storage.signed_download(key, filename=filename)
    if url:
        # 307 preserves the original GET; fetch follows it to storage.
        return RedirectResponse(url, status_code=307)
    data = storage.get_bytes(key)
    return Response(
        content=data,
        media_type=DOCX_MEDIA,
        headers=_attachment(filename) if filename else None,
    )


def generated_docx_response(
    data: bytes,
    *,
    owner_id: str | None,
    filename: str | None = None,
    storage: Storage | None = None,
) -> Response:
    """Serve freshly generated DOCX bytes (preview/fix), offloading large ones.

    Small payloads stream inline (fast, no storage write). Large payloads are
    parked at an ephemeral key and returned as a signed-URL redirect so they
    clear the body cap. If signed URLs aren't available (local backend) we stream
    regardless — there is no cap there.
    """
    storage = storage or get_storage()
    if len(data) > _INLINE_MAX_BYTES:
        try:
            key = join_key(_EPHEMERAL_PREFIX, owner_id or "anon", f"{new_uuid()}.docx")
            storage.put_bytes(key, data, content_type=DOCX_MEDIA)
            url = storage.signed_download(key, expires_in=900, filename=filename)
            if url:
                # 303 so the browser re-issues the POST target as a GET to storage.
                return RedirectResponse(url, status_code=303)
        except Exception:
            pass  # fall through to streaming
    return Response(
        content=data,
        media_type=DOCX_MEDIA,
        headers=_attachment(filename) if filename else None,
    )
