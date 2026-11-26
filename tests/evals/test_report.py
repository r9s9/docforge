"""Result files are written the same way on every platform."""

from __future__ import annotations

import subprocess

from evals.report import git_state, library_versions, write_result


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


def test_a_result_file_does_not_make_the_tree_dirty_but_a_code_change_does(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "evals" / "results").mkdir(parents=True)
    (tmp_path / "evals" / "harness.py").write_text("x = 1\n", encoding="utf-8")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")

    (tmp_path / "evals" / "results" / "2026-11-26_local_comply.json").write_text("{}\n")
    state = git_state(tmp_path)
    assert state["dirty"] is False and len(state["git_sha"]) == 40

    (tmp_path / "evals" / "harness.py").write_text("x = 2\n", encoding="utf-8")
    assert git_state(tmp_path)["dirty"] is True
