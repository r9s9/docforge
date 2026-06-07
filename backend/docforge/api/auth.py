"""Authentication: verify Supabase-issued JWTs and identify the current user.

DocForge uses Supabase Auth for accounts. The frontend obtains a session JWT from
Supabase and sends it as ``Authorization: Bearer <token>``. We verify that token
locally with the project's JWT secret (HS256) — no network call — and scope all
data to the resulting user id (the Supabase user UUID, the JWT ``sub`` claim).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, HTTPException

from ..config import Settings
from .deps import get_settings_dep

logger = logging.getLogger("docforge.api.auth")


@dataclass
class CurrentUser:
    id: str  # Supabase user UUID (JWT 'sub')
    email: str | None = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> CurrentUser:
    """Resolve the signed-in user from the Bearer token, or raise 401.

    When ``auth_required`` is off (e.g. a fully local single-user deployment) a
    fixed ``local`` user is returned so the app still works without Supabase.
    """
    if not settings.auth_required:
        return CurrentUser(id="local", email=None)

    if not settings.supabase_jwt_secret:
        # Misconfiguration: auth is required but no secret to verify with.
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()

    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience or None,
            options={"verify_aud": bool(settings.supabase_jwt_audience)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired — please sign in again") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Invalid authentication token") from exc

    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("Token has no subject")
    return CurrentUser(id=str(sub), email=claims.get("email"))
