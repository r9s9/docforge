"""Storage backends: round-trip behavior for local + Supabase (mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest

from docforge.storage.local import LocalStorage
from docforge.storage.supabase import SupabaseStorage


# --------------------------------------------------------------------------- #
# LocalStorage                                                                 #
# --------------------------------------------------------------------------- #
def test_local_roundtrip(tmp_path):
    st = LocalStorage(tmp_path)
    st.put_bytes("uploads/a.docx", b"hello")
    assert st.exists("uploads/a.docx")
    assert st.get_bytes("uploads/a.docx") == b"hello"

    st.put_json("templates/t/1/fields.json", [{"k": "v"}])
    assert st.get_json("templates/t/1/fields.json") == [{"k": "v"}]

    with st.local_path("uploads/a.docx") as p:
        assert p.exists() and p.read_bytes() == b"hello"

    assert not st.exists("uploads/missing.docx")


def test_local_list_and_delete_prefix(tmp_path):
    st = LocalStorage(tmp_path)
    for k in ("templates/t/1/template.docx", "templates/t/1/source_examples/x.docx",
              "templates/t/2/template.docx", "templates/other/1/template.docx"):
        st.put_bytes(k, b"x")

    keys = set(st.list_prefix("templates/t/"))
    assert keys == {
        "templates/t/1/template.docx",
        "templates/t/1/source_examples/x.docx",
        "templates/t/2/template.docx",
    }

    st.delete_prefix("templates/t/")
    assert st.list_prefix("templates/t/") == []
    assert st.exists("templates/other/1/template.docx")  # untouched


def test_local_stat_prefix(tmp_path):
    st = LocalStorage(tmp_path)
    st.put_bytes("generated/a.docx", b"12345")
    st.put_bytes("generated/b.docx", b"abc")
    stats = {k: size for k, size, _mtime in st.stat_prefix("generated/")}
    assert stats == {"generated/a.docx": 5, "generated/b.docx": 3}
    assert all(mtime is not None for _k, _s, mtime in st.stat_prefix("generated/"))


def test_local_rejects_escaping_key(tmp_path):
    st = LocalStorage(tmp_path)
    with pytest.raises(ValueError):
        st.put_bytes("../escape.txt", b"x")


# --------------------------------------------------------------------------- #
# SupabaseStorage (mocked Storage REST API)                                    #
# --------------------------------------------------------------------------- #
class _FakeBucket:
    """In-memory stand-in for the Supabase Storage REST API."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        # Auth headers must always be present.
        assert request.headers.get("apikey") == "svc-key"
        assert request.headers.get("authorization") == "Bearer svc-key"
        path = request.url.path
        prefix = "/storage/v1/object/"

        if path.startswith(prefix + "list/"):
            body = request.read()
            import json

            q = json.loads(body) if body else {}
            want = q.get("prefix", "")
            # one level: immediate children of `want`
            seen_files, seen_dirs = [], set()
            for key, data in self.objects.items():
                if not key.startswith(want):
                    continue
                rest = key[len(want):]
                head, _, tail = rest.partition("/")
                if tail:
                    seen_dirs.add(head)
                else:
                    seen_files.append({
                        "name": head,
                        "id": "file-id",
                        "updated_at": "2024-01-01T00:00:00.000Z",
                        "metadata": {"size": len(data)},
                    })
            entries = [{"name": d, "id": None} for d in sorted(seen_dirs)] + seen_files
            return httpx.Response(200, json=entries)

        # object ops: /object/{bucket}/{key...}
        rest = path[len(prefix):]
        bucket, _, key = rest.partition("/")
        assert bucket == "docforge"

        if request.method in ("PUT", "POST"):
            self.objects[key] = request.read()
            return httpx.Response(200, json={"Key": key})
        if request.method == "GET":
            if key not in self.objects:
                return httpx.Response(404, json={"error": "not found"})
            data = self.objects[key]
            if request.headers.get("Range"):
                return httpx.Response(206, content=data[:1])
            return httpx.Response(200, content=data)
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(200, json={})
        return httpx.Response(405)


def _make_supabase() -> tuple[SupabaseStorage, _FakeBucket]:
    bucket = _FakeBucket()
    st = SupabaseStorage("https://proj.supabase.co", "svc-key", "docforge")
    st._client = httpx.Client(
        transport=httpx.MockTransport(bucket.handler), headers=st._headers
    )
    return st, bucket


def test_supabase_strips_whitespace_in_credentials():
    """A pasted key/URL with a trailing newline must not produce illegal headers."""
    st = SupabaseStorage("https://proj.supabase.co\n", "svc-key\n", "docforge\n")
    assert st._headers["Authorization"] == "Bearer svc-key"
    assert st._headers["apikey"] == "svc-key"
    assert "\n" not in st._headers["Authorization"]
    assert st.base == "https://proj.supabase.co/storage/v1"
    assert st.bucket == "docforge"


def test_supabase_roundtrip():
    st, _ = _make_supabase()
    st.put_bytes("uploads/a.docx", b"hello", content_type="application/x")
    assert st.exists("uploads/a.docx")
    assert st.get_bytes("uploads/a.docx") == b"hello"

    st.put_json("templates/t/1/fields.json", {"k": "v"})
    assert st.get_json("templates/t/1/fields.json") == {"k": "v"}

    with st.local_path("uploads/a.docx") as p:
        assert p.read_bytes() == b"hello"
    assert not p.exists()  # temp file cleaned up

    assert not st.exists("uploads/missing.docx")
    with pytest.raises(FileNotFoundError):
        st.get_bytes("uploads/missing.docx")


def test_supabase_recursive_list_and_delete():
    st, _ = _make_supabase()
    for k in ("templates/t/1/template.docx", "templates/t/1/source_examples/x.docx",
              "templates/t/2/template.docx", "templates/other/1/template.docx"):
        st.put_bytes(k, b"x")

    keys = set(st.list_prefix("templates/t/"))
    assert keys == {
        "templates/t/1/template.docx",
        "templates/t/1/source_examples/x.docx",
        "templates/t/2/template.docx",
    }

    st.delete_prefix("templates/t/")
    assert st.list_prefix("templates/t/") == []
    assert st.exists("templates/other/1/template.docx")


def test_supabase_stat_prefix_carries_size():
    st, _ = _make_supabase()
    st.put_bytes("generated/a.docx", b"12345")
    st.put_bytes("generated/b.docx", b"abc")
    stats = {k: size for k, size, _mtime in st.stat_prefix("generated/")}
    assert stats == {"generated/a.docx": 5, "generated/b.docx": 3}
    assert all(mtime is not None for _k, _s, mtime in st.stat_prefix("generated/"))


def test_supabase_exists_raises_on_server_error():
    """A 5xx must surface, not be silently read as 'object absent'."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    st = SupabaseStorage("https://proj.supabase.co", "svc-key", "docforge")
    st._client = httpx.Client(transport=httpx.MockTransport(handler), headers=st._headers)
    with pytest.raises(OSError):
        st.exists("uploads/whatever.docx")


def test_retention_prunes_through_storage(tmp_path, monkeypatch):
    """prune_generated must delete generated objects via the storage layer."""
    from docforge.config import get_settings
    from docforge.services.retention import prune_generated
    from docforge.storage import GENERATED, get_storage, join_key

    s = get_settings()
    monkeypatch.setattr(s, "data_dir", tmp_path / "data")
    monkeypatch.setattr(s, "storage_backend", "local")
    monkeypatch.setattr(s, "generated_retention_days", -1)  # force everything "stale"
    monkeypatch.setattr(s, "generated_max_total_mb", 0)  # disable size cap

    st = get_storage()
    st.put_bytes(join_key(GENERATED, "old.docx"), b"data")
    assert st.list_prefix(GENERATED + "/")

    removed = prune_generated(s)
    assert removed == 1
    assert st.list_prefix(GENERATED + "/") == []
