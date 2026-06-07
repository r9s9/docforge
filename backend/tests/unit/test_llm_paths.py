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

        def stream_openai(self, messages, *, on_delta=None, temperature=0.0, cancel_event=None):
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


def test_classify_llm_batches_large_documents(tmp_path):
    # Large docs must be classified in batches so no single response is truncated;
    # every top-level element must still be covered, and sections requested once.
    from docx import Document

    from docforge.ai_classifier.llm import CLASSIFY_BATCH_SIZE, classify_llm

    doc = Document()
    for i in range(55):
        doc.add_paragraph(f"Field {i}: value{i}")
    p = tmp_path / "big.docx"
    doc.save(str(p))
    ext = build_extraction(str(p), "big")
    n = len(ext.top_level_elements())
    assert n > CLASSIFY_BATCH_SIZE  # ensures the batching path is exercised

    calls = {"n": 0, "sections": 0}

    class _BatchClient:
        model = "mock"
        active = True
        provider = "openai"
        supports_streaming = False

        def complete_json(self, *, system, developer, user, schema, cancel_event=None):
            import re

            calls["n"] += 1
            if "group them into sections" in user:
                calls["sections"] += 1
            ids = re.findall(r'"node_id": "([^"]+)"', user)
            return LLMClassifyResponse(
                document_type_guess="report" if calls["n"] == 1 else "",
                classifications=[
                    LLMElementClassification(node_id=i, classification="DYNAMIC_TEXT", field_name=f"f_{i}")
                    for i in ids
                ],
                sections=[],
            )

    res = classify_llm(ext, None, _BatchClient())
    from_llm = [c for c in res.classifications if c.source == "llm"]
    assert calls["n"] == -(-n // CLASSIFY_BATCH_SIZE)  # ceil division
    assert calls["sections"] == 1  # sections requested only on the first batch
    assert len(from_llm) >= n  # every top-level element classified by the model


def test_route_llm_filters_unknown_fields():
    fields = [FieldDefinition(field_name="known", label="Known", field_type=FieldType.TEXT, required=True)]
    resp = LLMRouteResponse(
        placements=[LLMPlacement(field_name="known", value="V"), LLMPlacement(field_name="bogus", value="X")]
    )
    res = route_llm(fields, raw_text="x", data=None, client=_FakeClient(resp), template_id="t", version=1)
    assert {p.field_name for p in res.placements} == {"known"}  # unknown field dropped


def test_route_llm_batches_large_templates():
    # Many fields must be routed in batches so a single response is never oversized;
    # every field should still get its placement.
    import re

    from docforge.ai_router.llm import ROUTE_BATCH_SIZE, route_llm

    n = ROUTE_BATCH_SIZE * 2 + 5  # force multiple batches regardless of the cap
    fields = [
        FieldDefinition(field_name=f"f_{i}", label=f"F{i}", field_type=FieldType.TEXT, required=False)
        for i in range(n)
    ]
    calls = {"n": 0}

    class _RouteBatchClient:
        model = "mock"
        active = True

        def complete_json(self, *, system, developer, user, schema, cancel_event=None):
            calls["n"] += 1
            names = re.findall(r'"field_name": "([^"]+)"', user)
            return LLMRouteResponse(
                placements=[LLMPlacement(field_name=nm, value=f"v_{nm}") for nm in names]
            )

    res = route_llm(fields, raw_text="content", data=None, client=_RouteBatchClient(),
                    template_id="t", version=1)
    assert calls["n"] == -(-n // ROUTE_BATCH_SIZE)  # ceil division -> batched
    assert len(res.placements) == n  # every field routed
    assert {p.field_name for p in res.placements} == {f.field_name for f in fields}


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


# --- Fix: lenient schema coercion (local models emit null for list/str fields) ---


def test_lenient_schema_coerces_null_lists_and_strings():
    # The exact shape Qwen3 returns that previously caused 12 validation errors.
    raw = {
        "document_type_guess": "report",
        "classifications": [
            {
                "node_id": "p1",
                "classification": "DYNAMIC_TEXT",
                "field_name": "name",
                "validation_hints": None,  # null -> []
                "enum_values": None,  # null -> []
                "rationale": None,  # null -> ""
            }
        ],
        "sections": None,  # null -> []
    }
    parsed = LLMClassifyResponse.model_validate(raw)
    c = parsed.classifications[0]
    assert c.enum_values == [] and c.validation_hints == [] and c.rationale == ""
    assert parsed.sections == []


def test_lenient_schema_coerces_route_nulls():
    raw = {
        "placements": [
            {"field_name": "x", "value": "v", "alternatives": None, "note": None, "source_excerpt": None}
        ],
        "missing_required": None,
        "ambiguous_fields": None,
        "unmapped_content": None,
    }
    parsed = LLMRouteResponse.model_validate(raw)
    assert parsed.missing_required == [] and parsed.placements[0].alternatives == []


# --- Fix: robust JSON extraction (truncation + unclosed think) ---


def test_extract_json_repairs_truncated_array():
    # finish_reason=length cut the response mid-third-object.
    truncated = (
        '{"document_type_guess":"x","classifications":'
        '[{"node_id":"a","confidence":0.9},{"node_id":"b","confidence":0.8},{"node_id":"c","confi'
    )
    data = _extract_json(truncated)
    assert data is not None
    ids = [c["node_id"] for c in data["classifications"]]
    assert "a" in ids and "b" in ids  # complete objects salvaged


def test_extract_json_handles_unclosed_think():
    assert _extract_json("<think>still reasoning, never finished") is None
    assert _extract_json("<think>plan</think>\n{\"a\":1}") == {"a": 1}


def test_extract_json_truncated_object_does_not_leak_inner_array():
    # Adversarial-review finding 3: a truncated top-level OBJECT must never be
    # salvaged as one of its inner arrays.
    out = _extract_json('{"items": [1,2,3], "name": "foo')
    assert isinstance(out, dict)
    assert out.get("items") == [1, 2, 3]


def test_extract_json_required_identifier_null_is_rejected():
    # Finding 1 end-to-end: a null node_id is a malformed signal — the schema
    # must reject it (so the repair loop retries) rather than coerce to "".
    import pytest
    from pydantic import ValidationError

    from docforge.ai.prompts import LLMElementClassification, LLMPlacement, LLMSection

    for model, kwargs in (
        (LLMElementClassification, {"node_id": None}),
        (LLMSection, {"section_key": None}),
        (LLMPlacement, {"field_name": None}),
    ):
        with pytest.raises(ValidationError):
            model(**kwargs)
    # …but optional strings still coerce null -> "".
    assert LLMElementClassification(node_id="x", description=None, rationale=None).description == ""


def test_repair_keeps_complete_objects_and_trailing_comma_primitive():
    # Finding 2: complete elements survive; an ambiguous bare final primitive
    # (no delimiter) is dropped, but a comma-terminated one is kept.
    assert _extract_json("[1, 2, 3, 4,") == [1, 2, 3, 4]
    assert _extract_json("[1, 2, 3, 4") == [1, 2, 3]
    assert _extract_json('["a","b","c"') == ["a", "b", "c"]


# --- Fix: cancellation aborts the stream (model server stops generating) ---


def test_stream_cancel_aborts_and_raises():
    import threading
    import time

    from docforge.ai.client import LLMCancelled

    class _SlowStream:
        status_code = 200

        def read(self):
            return None

        def iter_lines(self):
            for _ in range(10_000):
                time.sleep(0.005)
                yield 'data: {"choices":[{"delta":{"content":"x"}}]}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _SlowClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, *a, **k):
            return _SlowStream()

    import docforge.ai.client as client_mod

    orig = client_mod.httpx.Client
    client_mod.httpx.Client = _SlowClient
    try:
        client = LLMClient(_cfg())
        ev = threading.Event()
        out: dict = {}

        def run():
            try:
                client.stream_openai([{"role": "user", "content": "hi"}], cancel_event=ev)
                out["r"] = "completed"
            except LLMCancelled:
                out["r"] = "cancelled"
            except Exception as exc:  # pragma: no cover - diagnostic
                out["r"] = f"error:{exc}"

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.1)
        ev.set()
        t.join(timeout=3)
        assert out.get("r") == "cancelled"
    finally:
        client_mod.httpx.Client = orig
