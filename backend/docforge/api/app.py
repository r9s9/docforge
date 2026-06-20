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
)
from .routes import settings as settings_routes

logger = logging.getLogger("docforge.api")
req_logger = logging.getLogger("docforge.request")


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
    init_db()
    settings = get_settings()

    # Recover jobs orphaned by a previous crash/restart, and prune old outputs.
    from ..services import prune_generated
    from ..services.recovery import recover_stuck_jobs
    from ..settings_store import get_ai_config

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
        token = set_request_context(rid=rid, method=request.method, path=path)
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

    for module in (health, templates, projects, analyses, generations, compliance, settings_routes):
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
