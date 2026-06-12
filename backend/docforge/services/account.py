"""Delete a user account and ALL of its data + stored files.

This is the irreversible "delete my account" action. It purges every row a user
owns across the schema, removes the backing files (uploads, generated documents,
template packages) from storage, and — when Supabase is configured — deletes the
auth user via the admin API so the email can be reused.

Ordering is chosen so file deletes happen while we still hold the rows that point
at them; DB deletes then clear the rows. Everything is best-effort per artifact
so one missing file never blocks the account from being removed.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import (
    AIDecisionLog,
    AnalysisJob,
    ExtractedDocument,
    GeneratedDocument,
    GenerationRequest,
    Project,
    SourceDocument,
    Template,
    TemplateVersion,
    User,
    UserAIConfig,
)
from ..storage import get_storage
from ..template_registry import TemplateRegistry

logger = logging.getLogger("docforge.account")


def _delete_supabase_user(user_id: str, settings: Settings) -> bool:
    """Delete the Supabase auth user via the admin API (service-role key).

    Returns True on success. Best-effort: returns False (logged) when Supabase
    isn't configured or the call fails — the local data is purged regardless.
    """
    base = (settings.supabase_url or "").strip().rstrip("/")
    key = (settings.supabase_service_role_key or "").strip()
    if not base or not key or user_id in ("", "local"):
        return False
    try:
        r = httpx.delete(
            f"{base}/auth/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {key}", "apikey": key},
            timeout=15.0,
        )
        if r.status_code in (200, 204):
            return True
        logger.warning("Supabase user delete returned %s: %s", r.status_code, r.text[:200])
    except httpx.HTTPError as exc:  # network / config issue — non-fatal
        logger.warning("Supabase user delete failed: %s", exc)
    return False


def delete_account(
    db: Session,
    owner_id: str,
    *,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> dict:
    """Purge all data + files for ``owner_id`` and remove the auth user.

    Returns a small summary of what was removed.
    """
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)
    storage = get_storage()

    summary = {"templates": 0, "source_documents": 0, "generated_documents": 0, "projects": 0}

    # --- Template packages (files) + their version/request/output rows ---
    templates = db.query(Template).filter(Template.owner_id == owner_id).all()
    template_ids = [t.id for t in templates]
    for t in templates:
        try:
            registry.delete_template(t.id)  # removes the whole templates/<id>/ tree
        except Exception:
            logger.exception("failed to delete template package %s", t.id)
    summary["templates"] = len(templates)

    # --- Generated document output files (owned directly by the user) ---
    gens = db.query(GeneratedDocument).filter(GeneratedDocument.owner_id == owner_id).all()
    for g in gens:
        if g.output_path:
            try:
                storage.delete(g.output_path)
            except Exception:
                pass
    summary["generated_documents"] = len(gens)

    # --- Uploaded source files + their extractions ---
    sources = db.query(SourceDocument).filter(SourceDocument.owner_id == owner_id).all()
    source_ids = [s.id for s in sources]
    for s in sources:
        if s.stored_path:
            try:
                storage.delete(s.stored_path)
            except Exception:
                pass
    summary["source_documents"] = len(sources)

    # --- Database rows ---------------------------------------------------
    if source_ids:
        db.query(ExtractedDocument).filter(
            ExtractedDocument.source_document_id.in_(source_ids)
        ).delete(synchronize_session=False)
    if template_ids:
        db.query(TemplateVersion).filter(
            TemplateVersion.template_id.in_(template_ids)
        ).delete(synchronize_session=False)

    summary["projects"] = (
        db.query(Project).filter(Project.owner_id == owner_id).count()
    )

    # All owner-scoped tables (owner_id column) + the UserAIConfig (owner_id PK).
    for model in (
        GeneratedDocument,
        GenerationRequest,
        Template,
        AnalysisJob,
        SourceDocument,
        Project,
        AIDecisionLog,
        UserAIConfig,
    ):
        db.query(model).filter(model.owner_id == owner_id).delete(synchronize_session=False)

    # The local app profile row (Supabase is the source of truth for real users,
    # but a User row may exist for the workspace mapping).
    db.query(User).filter(User.id == owner_id).delete(synchronize_session=False)

    db.commit()

    auth_deleted = _delete_supabase_user(owner_id, settings)
    summary["auth_user_deleted"] = auth_deleted
    logger.info("account %s purged: %s", owner_id, summary)
    return summary
