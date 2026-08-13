"""What /health reports about AI, and who it reports it for."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from docforge.api.app import app
from docforge.api.auth import CurrentUser, get_current_user, get_optional_user
from docforge.api.deps import get_db
from docforge.settings_store import AIConfig

USER = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(db_session, settings_tmp):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _as_user(user: CurrentUser | None):
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user


def test_health_reports_the_ai_the_caller_would_actually_get(client, monkeypatch):
    # A user with their own key was being told the engine was "Heuristic",
    # because health answered from the global config while their work used theirs.
    from docforge.api.routes import health as health_route
    from docforge.ai_quota import AIPlan

    own = AIConfig(
        provider="openai", enabled=True, base_url="https://api.example.com",
        api_key="sk-user-key", model="gpt-user",
    )
    monkeypatch.setattr(
        health_route, "plan_ai_for_owner", lambda owner_id: AIPlan(config=own, mode="own")
    )
    _as_user(CurrentUser(id=USER, email="u@example.com"))

    body = client.get("/api/health").json()
    assert body["ai_active"] is True
    assert body["ai_model"] == "gpt-user"
    assert body["ai_provider"] == "openai"


def test_health_still_answers_before_sign_in(client, monkeypatch):
    # The login screen reaches it without a token; it must not 401.
    from docforge.api.routes import health as health_route

    monkeypatch.setattr(
        health_route, "get_ai_config",
        lambda: AIConfig(provider="openai", enabled=False, base_url="", api_key="", model=""),
    )
    _as_user(None)

    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ai_active"] is False


def test_health_says_when_pdf_export_is_unavailable(client, monkeypatch):
    # The UI hides the PDF button on this, so it has to be accurate: a serverless
    # host has no LibreOffice and the conversion can only ever fail there.
    from docforge.api.routes import health as health_route

    _as_user(None)
    monkeypatch.setattr(health_route, "pdf_available", lambda: False)
    assert client.get("/api/health").json()["pdf_export"] is False

    monkeypatch.setattr(health_route, "pdf_available", lambda: True)
    assert client.get("/api/health").json()["pdf_export"] is True


def test_a_bad_token_is_treated_as_signed_out_not_an_error(settings_tmp):
    # get_optional_user must swallow the 401 so health keeps answering.
    from docforge.api.auth import get_optional_user as resolve

    secured = settings_tmp.model_copy(
        update={"auth_required": True, "supabase_jwt_secret": "s" * 40}
    )
    assert resolve(authorization="Bearer nonsense", settings=secured) is None
    assert resolve(authorization=None, settings=secured) is None


def test_with_auth_disabled_everyone_is_the_local_user(settings_tmp):
    # A single-user local deployment has no tokens at all; health should still
    # report that user's AI rather than falling back to the global config.
    from docforge.api.auth import get_optional_user as resolve

    user = resolve(authorization=None, settings=settings_tmp)
    assert user is not None and user.id == "local"
