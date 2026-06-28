"""Vercel Python entrypoint.

Vercel's FastAPI preset discovers a module-level ``app`` in ``main.py`` (at the
project Root Directory, which is ``backend/``) and serves the whole ASGI app as a
single Vercel Function. All DocForge routes are under ``/api``, so the browser
calls ``<backend-url>/api/...`` and FastAPI matches them directly.

Nothing else belongs here — configuration is environment-driven (see config.py),
and table creation/maintenance is gated off in serverless mode (see app.py).
"""

from __future__ import annotations

from docforge.api.app import app  # noqa: F401  (re-exported for Vercel)
