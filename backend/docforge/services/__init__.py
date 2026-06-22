"""Cross-module orchestration services (use cases)."""

from __future__ import annotations

from .analysis import analyze_documents, run_analysis_job, start_analysis
from .audit import record_decision
from .compliance import check_document
from .compliance_fix import fix_document
from .generation import generate_document, preview_document, render_preview_docx, route_document
from .preview_docx import build_job_preview_docx, build_template_edit_preview_docx
from .publish import publish_template
from .republish import republish_template
from .retention import prune_generated
from .seed import seed_demo_templates

__all__ = [
    "analyze_documents",
    "start_analysis",
    "run_analysis_job",
    "record_decision",
    "publish_template",
    "republish_template",
    "generate_document",
    "preview_document",
    "render_preview_docx",
    "route_document",
    "build_job_preview_docx",
    "build_template_edit_preview_docx",
    "check_document",
    "fix_document",
    "seed_demo_templates",
    "prune_generated",
]
