"""Authentication: verify Supabase-issued JWTs and identify the current user.

DocForge uses Supabase Auth for accounts. The frontend obtains a session JWT from
Supabase and sends it as ``Authorization: Bearer <token>``. We verify that token
locally and scope all data to the resulting user id (the Supabase user UUID, the
JWT ``sub`` claim).

Two signing schemes are supported, chosen per-token by the header ``alg``:
  * **HS256** — legacy projects with a shared "JWT secret"
    (``supabase_jwt_secret``); verified locally, no network call.
  * **ES256 / RS256 / EdDSA** — newer projects using "JWT Signing Keys"
    (asymmetric). The public keys are fetched from the project's JWKS endpoint
    (``<supabase_url>/auth/v1/.well-known/jwks.json``) and cached by key id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWK

from ..config import Settings
from .deps import get_settings_dep

logger = logging.getLogger("docforge.api.auth")

# Cache of JWKS keys by endpoint URL: {jwks_url: {kid: jwk_dict}}.
_jwks_cache: dict[str, dict[str, dict]] = {}


@dataclass
class CurrentUser:
    id: str  # Supabase user UUID (JWT 'sub')
    email: str | None = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _fetch_jwks(url: str) -> dict[str, dict]:
    """Fetch a JWKS document and index its keys by ``kid``."""
    r = httpx.get(url, timeout=10.0)
    r.raise_for_status()
    return {k["kid"]: k for k in r.json().get("keys", []) if k.get("kid")}


def _jwks_keys(url: str, *, force: bool = False) -> dict[str, dict]:
    if force or url not in _jwks_cache:
        _jwks_cache[url] = _fetch_jwks(url)
    return _jwks_cache[url]


def _verify_token(token: str, settings: Settings) -> dict:
    """Verify ``token`` against the project's signing scheme; return its claims."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")
    audience = settings.supabase_jwt_audience or None
    options = {"verify_aud": bool(audience)}

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("HS256 token but no JWT secret is configured")
        return jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"],
            audience=audience, options=options,
        )

    # Asymmetric (Supabase JWT Signing Keys): resolve the public key via JWKS.
    if not settings.supabase_url:
        raise jwt.InvalidTokenError("asymmetric token but supabase_url is not configured")
    jwks_url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    kid = header.get("kid")
    jwk = _jwks_keys(jwks_url).get(kid)
    if jwk is None:  # unknown key id -> refresh once (keys rotate)
        jwk = _jwks_keys(jwks_url, force=True).get(kid)
    if jwk is None:
        raise jwt.InvalidTokenError("no matching JWKS key for token")
    signing_key = PyJWK.from_dict(jwk).key
    return jwt.decode(
        token, signing_key, algorithms=[alg], audience=audience, options=options
    )


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

    # Need a way to verify: either a shared secret (HS256) or the project URL
    # (for the JWKS endpoint, asymmetric keys).
    if not settings.supabase_jwt_secret and not settings.supabase_url:
        raise HTTPException(status_code=503, detail="Authentication is not configured on the server")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()

    try:
        claims = _verify_token(token, settings)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expired — please sign in again") from exc
    except (jwt.InvalidTokenError, httpx.HTTPError, KeyError, ValueError) as exc:
        logger.debug("token verification failed: %s", exc)
        raise _unauthorized("Invalid authentication token") from exc

    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("Token has no subject")
    return CurrentUser(id=str(sub), email=claims.get("email"))
