"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..config import get_settings
from ..db.session import init_db
from ..logging_setup import configure_logging
from .routes import (
    analyses,
    compliance,
    generations,
    health,
    templates,
)
from .routes import settings as settings_routes

logger = logging.getLogger("docforge.api")


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

    for module in (health, templates, analyses, generations, compliance, settings_routes):
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
