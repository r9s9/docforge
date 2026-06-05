"""Offline tests for the LLM paths (transport, repair loop, provider mapping,
and the classify/route response mapping) using mocks — no network required.
"""

from __future__ import annotations

import httpx

from docforge.ai.client import LLMClient, _extract_json
from docforge.ai.prompts import (
    LLMClassifyResponse,
    LLMElementClassification,
    LLMPlacement,
    LLMRouteResponse,
)
from docforge.ai_classifier.llm import classify_llm
from docforge.ai_router.document import route_document_content
from docforge.ai_router.llm import route_llm
from docforge.schemas.enums import FieldType
from docforge.schemas.template import FieldDefinition
from docforge.settings_store import AIConfig
from docforge.structure_normalizer import build_extraction


class _Resp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code)
            )


def _cfg(provider="openai"):
    base = "http://x/v1" if provider == "openai" else "http://x"
    return AIConfig(provider=provider, enabled=True, base_url=base, api_key="k", model="m")


class _FakeClient:
    model = "mock-model"
    active = True

    def __init__(self, response):
        self._response = response

    def complete_json(self, **kwargs):
        return self._response


# --- transport / parsing ---------------------------------------------------
def test_extract_json_handles_fences_and_prose():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('here: {"a": 2} done') == {"a": 2}
    assert _extract_json("no json here") is None


def test_complete_json_repairs_after_invalid(monkeypatch):
    client = LLMClient(_cfg())
    seq = iter(["totally not json", '{"document_type_guess":"D","classifications":[],"sections":[]}'])
    monkeypatch.setattr(client, "complete", lambda messages, **kw: next(seq))
    res = client.complete_json(system="s", developer="d", user="u", schema=LLMClassifyResponse)
    assert res.document_type_guess == "D"


def test_openai_json_mode_400_falls_back(monkeypatch):
    calls = {"n": 0}

    def fake_post(self, url, **kw):
        calls["n"] += 1
        if "response_format" in kw.get("json", {}):
            return _Resp(400, {"error": "json mode unsupported"})
        return _Resp(200, {"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = LLMClient(_cfg()).complete([{"role": "user", "content": "hi"}], json_mode=True)
    assert out == "OK"
    assert calls["n"] == 2  # 400 then retry without response_format


def test_anthropic_message_mapping(monkeypatch):
    def fake_post(self, url, **kw):
        assert url.endswith("/v1/messages")
        assert kw["headers"]["anthropic-version"]
        return _Resp(200, {"content": [{"type": "text", "text": "hello world"}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = LLMClient(_cfg("anthropic")).complete(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    )
    assert out == "hello world"


# --- response mapping ------------------------------------------------------
def test_classify_llm_maps_response(project_docs):
    ext = build_extraction(project_docs[0], "d0")
    nid = ext.top_level_elements()[1].node_id
    resp = LLMClassifyResponse(
        document_type_guess="My Type",
        classifications=[
            LLMElementClassification(
                node_id=nid, classification="DYNAMIC_TEXT", field_name="foo", field_type="text", confidence=0.9
            )
        ],
    )
    result = classify_llm(ext, None, _FakeClient(resp))
    assert result.source == "llm"
    assert result.document_type_guess == "My Type"
    assert any(c.field_name == "foo" and c.classification.value == "DYNAMIC_TEXT" for c in result.classifications)


def test_classify_llm_streaming_reports_progress(project_docs):
    ext = build_extraction(project_docs[0], "d0")
    nid = ext.top_level_elements()[1].node_id
    payload = (
        '{"document_type_guess":"Streamed","classifications":[{"node_id":"'
        + nid
        + '","classification":"DYNAMIC_TEXT","field_name":"foo","field_type":"text"}],"sections":[]}'
    )

    class StreamingClient:
        model = "mock"
        active = True
        provider = "openai"
        supports_streaming = True

        def stream_openai(self, messages, *, on_delta=None, temperature=0.0):
            acc = ""
            for ch in payload:
                acc += ch
                if on_delta:
                    on_delta(ch, acc)
            return payload

    progress: list[float] = []
    res = classify_llm(ext, None, StreamingClient(), on_progress=lambda d, f: progress.append(f))
    assert res.document_type_guess == "Streamed"
    assert any(c.field_name == "foo" for c in res.classifications)
    assert progress and progress[-1] == 1.0  # streamed to completion


def test_route_llm_filters_unknown_fields():
    fields = [FieldDefinition(field_name="known", label="Known", field_type=FieldType.TEXT, required=True)]
    resp = LLMRouteResponse(
        placements=[LLMPlacement(field_name="known", value="V"), LLMPlacement(field_name="bogus", value="X")]
    )
    res = route_llm(fields, raw_text="x", data=None, client=_FakeClient(resp), template_id="t", version=1)
    assert {p.field_name for p in res.placements} == {"known"}  # unknown field dropped


def test_classify_llm_applies_optional_from_diff(tmp_path):
    # Optional detection is diff-driven and must hold even when the LLM classifies
    # the node as plain FIXED.
    from docforge.multi_doc_differ import diff_documents
    from docforge.sampledata import build_service_agreement

    p1 = tmp_path / "sa1.docx"
    build_service_agreement(1).save(str(p1))  # has the optional special clause
    p2 = tmp_path / "sa2.docx"
    build_service_agreement(2).save(str(p2))  # omits it
    e1 = build_extraction(str(p1), "a")
    e2 = build_extraction(str(p2), "b")
    diff = diff_documents([e1, e2])
    optional_node = next(d for d in diff.node_diffs if d.is_optional)

    resp = LLMClassifyResponse(
        classifications=[
            LLMElementClassification(node_id=optional_node.representative_node_id, classification="FIXED")
        ]
    )
    result = classify_llm(e1, diff, _FakeClient(resp))
    c = next(c for c in result.classifications if c.node_id == optional_node.representative_node_id)
    assert c.optional is True


def test_route_document_content_uses_llm_when_active():
    fields = [FieldDefinition(field_name="title", label="Title", field_type=FieldType.TEXT, required=True)]
    resp = LLMRouteResponse(placements=[LLMPlacement(field_name="title", value="Hello")])
    content = {"paragraphs": ["Title: Hello"], "tables": []}
    res = route_document_content(fields, content, template_id="t", version=1, client=_FakeClient(resp))
    assert {p.field_name: p.value for p in res.placements}.get("title") == "Hello"
    assert res.source == "llm"
