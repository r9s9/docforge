"""Seed demo templates (spec §16 Phase 5): build the three example template
packages end-to-end so a fresh install has something to explore.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db.models import Template
from ..document_ingest import store_source_document
from ..sampledata import write_all
from ..template_registry import TemplateRegistry
from .analysis import analyze_documents
from .publish import publish_template

logger = logging.getLogger("docforge.seed")

_DISPLAY_NAMES = {
    "project_report": "Monthly Project Status Report",
    "invoice": "Invoice",
    "compliance_report": "Compliance Audit Report",
}


def seed_demo_templates(
    db: Session,
    *,
    settings: Settings | None = None,
    registry: TemplateRegistry | None = None,
) -> list[Template]:
    """Generate sample docs, analyze and publish each as a demo template."""
    settings = settings or get_settings()
    registry = registry or TemplateRegistry(settings.templates_dir)

    tmp = Path(tempfile.mkdtemp(prefix="docforge-seed-"))
    paths = write_all(tmp)

    templates: list[Template] = []
    for kind, files in paths.items():
        name = _DISPLAY_NAMES.get(kind, kind)
        sources = [store_source_document(db, p.name, p.read_bytes()) for p in files]
        job = analyze_documents(db, sources, settings=settings, name=name)
        template, _ = publish_template(db, job, name=name, settings=settings, registry=registry)
        templates.append(template)
        logger.info("Seeded template %s (%s)", template.id, name)
    return templates
