"""The committed manifest matches a fresh build, and the case plan meets the brief's rules."""

from __future__ import annotations

import copy
from collections import Counter, defaultdict

import pytest

from evals.corpus.build import (
    BASES_PER_MUTATOR,
    BuildError,
    build_corpus,
    corpus_hash,
    stale_files,
    truth_for,
    truth_hash,
)
from evals.corpus.doc_types import SPECS
from evals.corpus.mutators import applicable
from evals.paths import MANIFEST_PATH


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    manifest = build_corpus(out / "build", out / "manifest.json")
    return out, manifest


def test_committed_manifest_matches_a_fresh_build(fresh):
    out, _manifest = fresh
    assert (out / "manifest.json").read_text(encoding="utf-8") == MANIFEST_PATH.read_text(
        encoding="utf-8"
    ), "evals/corpus/manifest.json is stale: run `python -m evals corpus build`"


def test_case_ids_are_unique(fresh):
    _out, manifest = fresh
    counts = Counter(case["id"] for case in manifest["cases"])
    assert [case_id for case_id, n in counts.items() if n > 1] == []


def test_at_least_a_fifth_of_cases_are_clean_controls(fresh):
    _out, manifest = fresh
    clean = [case for case in manifest["cases"] if case["label"]["mutator"] == "none"]
    assert len(clean) / len(manifest["cases"]) >= 0.20


def test_each_mutator_is_applied_to_distinct_held_out_bases(fresh):
    _out, manifest = fresh
    bases = defaultdict(list)
    for case in manifest["cases"]:
        bases[(case["pair"], case["label"]["mutator"])].append(case["base"])
    for pair, spec in SPECS.items():
        assert len(bases[(pair, "none")]) == len(manifest["types"][pair]["held_out"])
        for name in applicable(spec):
            used = bases[(pair, name)]
            assert len(used) == len(set(used)) == BASES_PER_MUTATOR, (pair, name, used)
            assert all(base.startswith("held_") for base in used)


def test_every_built_file_matches_its_hash(fresh):
    out, manifest = fresh
    assert stale_files(manifest, out / "build") == []


def test_corpus_hash_covers_labels_and_files(fresh):
    _out, manifest = fresh
    assert manifest["corpus_hash"] == corpus_hash(manifest)
    tampered = copy.deepcopy(manifest)
    tampered["cases"][-1]["label"]["material"] = not tampered["cases"][-1]["label"]["material"]
    assert corpus_hash(tampered) != manifest["corpus_hash"]


@pytest.mark.parametrize("pair", sorted(SPECS))
def test_rebuilt_ground_truth_matches_the_manifest(fresh, pair):
    _out, manifest = fresh
    for name in ("ex_01", "held_08"):
        recorded = manifest["types"][pair]["documents"][name]["truth_hash"]
        assert truth_hash(truth_for(pair, name)) == recorded


def test_a_directory_not_made_by_the_build_is_never_overwritten(tmp_path):
    (tmp_path / "keep.txt").write_text("not ours")
    with pytest.raises(BuildError, match="not made by"):
        build_corpus(tmp_path)
    assert (tmp_path / "keep.txt").read_text() == "not ours"
