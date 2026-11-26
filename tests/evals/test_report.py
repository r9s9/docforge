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


def test_the_git_state_says_which_files_changed_and_whether_run_code_did(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    def write(path, text):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")

    git("init", "-q")
    write("evals/harness.py", "x = 1\n")
    write(".claude/launch.json", "{}\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")

    write("evals/results/2026-11-26_local_comply.json", "{}\n")  # a result: not a change
    state = git_state(tmp_path)
    assert len(state["git_sha"]) == 40
    assert (state["dirty"], state["dirty_code"], state["changed_files"],
            state["untracked_files"]) == (False, False, [], 0)

    # What the owner's PC had during M2: an editor setting and a note file. Not run code.
    write(".claude/launch.json", '{"edited": true}\n')
    write("my notes.txt", "private\n")
    state = git_state(tmp_path)
    assert (state["dirty"], state["dirty_code"], state["changed_files"],
            state["untracked_files"]) == (True, False, [".claude/launch.json"], 1)
    assert "my notes.txt" not in str(state)  # untracked names are never recorded

    write("evals/harness.py", "x = 2\n")
    state = git_state(tmp_path)
    assert state["dirty_code"] is True
    assert state["changed_files"] == [".claude/launch.json", "evals/harness.py"]

    git("mv", "evals/harness.py", "evals/sandbox.py")  # a rename lists the new path only
    assert git_state(tmp_path)["changed_files"] == [".claude/launch.json", "evals/sandbox.py"]
