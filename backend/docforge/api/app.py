"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import get_settings
from ..db.session import init_db
from ..logging_setup import (
    configure_logging,
    log_event,
    reset_request_context,
    set_request_context,
)
from .routes import (
    analyses,
    compliance,
    generations,
    health,
    projects,
    templates,
    uploads,
)
from .routes import settings as settings_routes

logger = logging.getLogger("docforge.api")
req_logger = logging.getLogger("docforge.request")


def _log_user(request: Request) -> str | None:
    """Best-effort user label for logging (NOT auth): the JWT 'sub', or 'local'.

    Decoded without signature verification — it only tags log lines so a user can
    see their own activity. Access control stays with get_current_user.
    """
    settings = get_settings()
    if not settings.auth_required:
        return "local"
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        import jwt

        claims = jwt.decode(auth.split(" ", 1)[1].strip(), options={"verify_signature": False})
        sub = claims.get("sub")
        return str(sub) if sub else None
    except Exception:
        return None


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes.

    Lets deep links like /templates/<id> and page refreshes work when the built
    SPA is served directly by FastAPI (Docker/production), without shadowing /api.
    """

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    from ..settings_store import get_ai_config

    # On serverless the process is frozen after each response and re-created per
    # cold start, so creating tables + running maintenance on every boot is both
    # wasteful and unsafe (concurrent cold starts racing DDL). Skip it; run
    # `docforge initdb` (or Alembic) once, out of band. See the deploy guide.
    if settings.serverless:
        logger.info(
            "DocForge API started (serverless, env=%s, ai_active=%s)",
            settings.env, get_ai_config().active,
        )
        yield
        return

    init_db()

    # Recover jobs orphaned by a previous crash/restart, and prune old outputs.
    from ..services import prune_generated
    from ..services.recovery import recover_stuck_jobs

    try:
        n = recover_stuck_jobs()
        if n:
            logger.warning("Marked %d orphaned job(s) as failed on startup", n)
        prune_generated()
    except Exception:
        logger.debug("startup maintenance failed", exc_info=True)

    logger.info(
        "DocForge API started (env=%s, ai_active=%s)", settings.env, get_ai_config().active
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="DocForge API",
        version=__version__,
        description="AI-powered DOCX reverse-engineering and document assembly platform",
        lifespan=lifespan,
    )

    # CORS — restrict to the configured frontend origin(s) in production; defaults
    # to "*" for local dev. Bearer token travels in a header (not cookies), so
    # credentials stay disabled.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging: stamp a short correlation id on every request and log its
    # method/path/status/duration. Downstream logs (services, AI calls) inherit
    # the same `rid`, so one request can be traced end to end. Health checks are
    # logged at DEBUG to avoid flooding the log on a poller.
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        path = request.url.path
        # Resolve the user up front (cheap, unverified token decode) so EVERY log
        # for this request — including these request.* lines — is attributed to
        # them. (BaseHTTPMiddleware runs the route in a child context, so a user
        # set inside the auth dependency would not flow back here.) Real auth is
        # still enforced by get_current_user; this label is for logging only.
        token = set_request_context(
            rid=rid, method=request.method, path=path, user=_log_user(request)
        )
        is_health = path.endswith("/health")
        start = time.perf_counter()
        level = logging.DEBUG if is_health else logging.INFO
        log_event(
            req_logger, "request.start", level=level,
            method=request.method, path=path,
            client=request.client.host if request.client else "?",
        )
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as exc:  # log, then let FastAPI's handlers produce the 500
            log_event(
                req_logger, "request.error", level=logging.ERROR,
                method=request.method, path=path,
                error=type(exc).__name__, detail=str(exc)[:200],
                ms=round((time.perf_counter() - start) * 1000, 1),
            )
            raise
        finally:
            log_event(
                req_logger, "request.done",
                level=logging.DEBUG if is_health else (
                    logging.WARNING if status >= 500 else logging.INFO
                ),
                method=request.method, path=path, status=status,
                ms=round((time.perf_counter() - start) * 1000, 1),
            )
            reset_request_context(token)

    # Turn any unhandled exception into a JSON 500 *handled by the app*, so it
    # flows back through CORSMiddleware and carries Access-Control-Allow-Origin.
    # Without this, a raw 500 reaches the browser with no CORS headers and shows
    # up as an opaque "NetworkError" instead of the real error.
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        log_event(
            req_logger, "request.unhandled", level=logging.ERROR,
            method=request.method, path=request.url.path,
            error=type(exc).__name__, detail=str(exc)[:300],
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}"},
        )

    for module in (
        health, templates, projects, analyses, generations, compliance, uploads, settings_routes
    ):
        app.include_router(module.router, prefix="/api")

    # Optionally serve a built frontend (Docker/production). Mounted last so it
    # never shadows /api routes.
    static_dir = os.environ.get("DOCFORGE_STATIC_DIR")
    candidate = Path(static_dir) if static_dir else Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if candidate.exists():
        app.mount("/", SPAStaticFiles(directory=str(candidate), html=True), name="frontend")
        logger.info("Serving frontend from %s", candidate)

    return app


app = create_app()
