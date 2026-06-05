"""End-to-end API tests via FastAPI TestClient (spec §15 endpoints)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docforge.api.app import app
from docforge.api.deps import get_db

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client(db_session, settings_tmp):
    """TestClient with the DB dependency pointed at the isolated test session.

    Instantiated without the lifespan context so the module-level engine/init_db
    is never touched; file storage is redirected by the settings_tmp fixture.
    """

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _upload(client, docs):
    files = [("files", (p.name, p.read_bytes(), DOCX)) for p in docs]
    return client.post("/api/templates/analyze", files=files)


def _publish_via_services(db, settings, docs, name="Template"):
    """Build a published template directly via the service layer.

    Analysis runs in a background thread that uses the *real* engine, so it
    can't see the TestClient's isolated session — we exercise the HTTP lifecycle
    endpoints against a template created synchronously here instead.
    """
    from pathlib import Path

    from docforge.document_ingest import store_source_document
    from docforge.services import analyze_documents, publish_template
    from docforge.template_registry import TemplateRegistry

    sources = [store_source_document(db, p.name, Path(p).read_bytes()) for p in docs]
    job = analyze_documents(db, sources, settings=settings)
    registry = TemplateRegistry(settings.templates_dir)
    template, _ = publish_template(db, job, name=name, settings=settings, registry=registry)
    return template.id


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_analyze_accepts_and_queues(client, project_docs):
    r = _upload(client, project_docs)
    assert r.status_code == 202, r.text
    assert r.json()["status"] in ("pending", "running", "completed")


def test_full_lifecycle(client, db_session, settings_tmp, project_docs):
    template_id = _publish_via_services(db_session, settings_tmp, project_docs, "Project Report")

    # browse
    assert any(t["id"] == template_id for t in client.get("/api/templates").json())
    detail = client.get(f"/api/templates/{template_id}").json()
    assert detail["latest"]["fields"]
    versions = client.get(f"/api/templates/{template_id}/versions").json()
    assert versions[0]["version"] == 1

    # 4) generate (structured)
    body = {
        "mode": "structured_json",
        "data": {
            "project_name": "Orion",
            "report_date": "2026-07-01",
            "prepared_by": "Alice Brown",
            "summary": "On track.",
            "task_status": [
                {"task": "Design", "owner": "M. Lee", "status": "Done", "due_date": "2026-07-01"},
            ],
        },
    }
    r = client.post(f"/api/templates/{template_id}/generate", json=body)
    assert r.status_code == 200, r.text
    gen = r.json()
    assert gen["validation"]["status"] == "pass"

    # 5) download the generated docx
    dl = client.get(gen["download_url"])
    assert dl.status_code == 200
    assert len(dl.content) > 1000
    assert "wordprocessingml" in dl.headers["content-type"]

    # 6) download the template docx
    tdl = client.get(f"/api/templates/{template_id}/versions/1/template.docx")
    assert tdl.status_code == 200


def test_route_and_validate(client, db_session, settings_tmp, project_docs):
    template_id = _publish_via_services(db_session, settings_tmp, project_docs, "PR")

    # route preview (unstructured)
    r = client.post(
        f"/api/templates/{template_id}/route",
        json={"raw_text": "Project Name: Helios\nReport Date: 2026-08-01\nGoing well."},
    )
    assert r.status_code == 200
    placements = {p["field_name"]: p["value"] for p in r.json()["placements"]}
    assert placements.get("project_name") == "Helios"

    # validate a deliberately incomplete context -> fail
    r = client.post(f"/api/templates/{template_id}/validate", json={"context": {"project_name": "X"}})
    assert r.status_code == 200
    assert r.json()["status"] in ("fail", "warning")


def test_rename_and_delete_template(client, db_session, settings_tmp, project_docs):
    template_id = _publish_via_services(db_session, settings_tmp, project_docs, "Original Name")

    # rename
    r = client.patch(f"/api/templates/{template_id}", json={"name": "Renamed Template"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Template"

    # delete
    r = client.delete(f"/api/templates/{template_id}")
    assert r.status_code == 204
    assert client.get(f"/api/templates/{template_id}").status_code == 404
    assert all(t["id"] != template_id for t in client.get("/api/templates").json())


def test_analyze_rejects_too_many_files(client, project_docs, monkeypatch, settings_tmp):
    monkeypatch.setattr(settings_tmp, "max_files_per_analysis", 1)
    r = _upload(client, project_docs)  # 2 files, limit 1
    assert r.status_code == 400
