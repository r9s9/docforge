"""Result files are written the same way on every platform."""

from __future__ import annotations

from evals.report import library_versions, write_result


def test_result_files_use_unix_line_endings(tmp_path):
    result = {"meta": {"date": "2026-11-26", "config": "no-ai", "suite": "comply"},
              "cases": [{"id": "a"}, {"id": "b"}]}
    path = write_result(result, tmp_path)
    assert path.name == "2026-11-26_no-ai_comply.json"
    assert b"\r\n" not in path.read_bytes()


def test_library_versions_name_the_corpus_and_client_libraries():
    versions = library_versions()
    assert set(versions) == {"python-docx", "lxml", "anthropic", "httpx", "httpx2"}
    assert versions["python-docx"]
