"""Tests for the added features: compliance, pre-generate preview, AI settings."""

from __future__ import annotations

from pathlib import Path

from docforge.document_ingest import store_source_document
from docforge.schemas.enums import GenerationMode
from docforge.schemas.generation import GenerationInput
from docforge.services import (
    analyze_documents,
    check_document,
    preview_document,
    publish_template,
    republish_template,
    route_document,
)
from docforge.settings_store import get_ai_config, update_ai_config
from docforge.template_registry import TemplateRegistry


def _publish(db, settings, docs, name):
    sources = [store_source_document(db, p.name, Path(p).read_bytes()) for p in docs]
    job = analyze_documents(db, sources, settings=settings)
    registry = TemplateRegistry(settings.templates_dir)
    template, _ = publish_template(db, job, name=name, settings=settings, registry=registry)
    return template, registry


def test_compliance_same_type_scores_high(db_session, settings_tmp, project_docs):
    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    report = check_document(
        db_session, template, filename="pr2.docx",
        data=Path(project_docs[1]).read_bytes(), settings=settings_tmp, registry=registry,
    )
    assert report.score >= 80
    assert report.grade in ("pass", "warning")
    assert "project_name" in report.matched_fields


def test_compliance_wrong_type_scores_low(db_session, settings_tmp, project_docs, invoice_docs):
    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    report = check_document(
        db_session, template, filename="inv.docx",
        data=Path(invoice_docs[0]).read_bytes(), settings=settings_tmp, registry=registry,
    )
    assert report.score < 80
    assert any(
        d.kind in ("missing_fixed", "missing_field", "missing_table", "changed_fixed")
        for d in report.differences
    )


def test_preview_returns_filled_blocks(db_session, settings_tmp, project_docs):
    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    gen_input = GenerationInput(
        mode=GenerationMode.STRUCTURED_JSON,
        data={
            "project_name": "Zeta",
            "report_date": "2026-07-01",
            "prepared_by": "A B",
            "summary": "ok",
            "task_status": [{"task": "t", "owner": "o", "status": "done", "due_date": "2026-07-01"}],
        },
    )
    preview = preview_document(template, gen_input, settings=settings_tmp, registry=registry)
    texts = [b.get("text", "") for b in preview["blocks"]]
    assert any("Project Name: Zeta" in t for t in texts)
    assert preview["validation"]["status"] == "pass"
    assert any(b["type"] == "table" for b in preview["blocks"])


def test_compliance_includes_document_preview(db_session, settings_tmp, project_docs):
    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    report = check_document(
        db_session, template, filename="pr2.docx",
        data=Path(project_docs[1]).read_bytes(), settings=settings_tmp, registry=registry,
    )
    assert report.document_preview
    assert any(b["type"] == "table" for b in report.document_preview)


def test_route_document_maps_uploaded_content(db_session, settings_tmp, project_docs):
    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    result = route_document(
        db_session, template, filename="pr2.docx",
        data=Path(project_docs[1]).read_bytes(), settings=settings_tmp, registry=registry,
    )
    placements = {p["field_name"]: p["value"] for p in result["routing"]["placements"]}
    assert "project_name" in placements
    assert "task_status" in placements  # table matched by header similarity
    assert isinstance(placements["task_status"], list) and placements["task_status"]
    assert any(b["type"] == "table" for b in result["extracted"])


def test_republish_edit_fields_creates_v2(db_session, settings_tmp, project_docs):
    from io import BytesIO

    from docx import Document

    template, registry = _publish(db_session, settings_tmp, project_docs, "PR")
    fields = registry.load_fields(template.id, 1)
    for f in fields:
        if f.field_name == "project_name":
            f.field_name = "proj"
            f.label = "Proj"

    template2, v2 = republish_template(
        db_session, template, fields=fields, settings=settings_tmp, registry=registry
    )
    assert v2.version == 2
    assert template2.latest_version == 2

    # the rebuilt template uses the renamed placeholder
    doc = Document(BytesIO(registry.template_docx_bytes(template.id, 2)))
    body = "\n".join(p.text for p in doc.paragraphs)
    assert "{{ proj }}" in body

    names = {f.field_name for f in registry.load_fields(template.id, 2)}
    assert "proj" in names and "project_name" not in names


def test_ai_settings_store_roundtrip(settings_tmp):
    assert get_ai_config().active is False
    update_ai_config(
        {"provider": "anthropic", "enabled": True, "model": "claude-3-5-sonnet", "api_key": "sk-test"}
    )
    cfg = get_ai_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-3-5-sonnet"
    assert cfg.active is True

    # A blank api_key on a later update must not wipe the stored key.
    update_ai_config({"enabled": False})
    cfg2 = get_ai_config()
    assert cfg2.api_key == "sk-test"
    assert cfg2.enabled is False
