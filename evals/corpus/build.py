"""Build the whole corpus: every document, every mutated case, and ``manifest.json``.

Layout of the build directory (gitignored, rebuilt at will)::

    build/<pair>/<doc_id>.docx               clean documents (ex_01..ex_05, held_01..held_08)
    build/<pair>/cases/<base>__<mutator>.docx mutated copies of held-out documents

The manifest (committed) lists every document with its field values, content hash and
ground-truth hash, and every comply case with its label. Clean controls point at the held-out
document itself. The full ground truth isn't stored: ``truth_for`` rebuilds it from the
generator, and the hashes in the manifest prove it is the same one.

The manifest's ``analyze`` section (M4) holds what only the analyze suite uses: the examples of
the analyze-only types, and one shared-value document per type (``shared_02``: the second
example with one value copied from the first). It has its own ``analyze_hash``, and
``corpus_hash`` leaves it out, so the corpus that comply and generate run on keeps its hash.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from evals import jsonfmt
from evals.corpus.doc_types import ALL_SPECS, ANALYZE_SPECS, SHARED_FIELDS, SPECS
from evals.corpus.generator import EXAMPLES, HELD_OUT, build_document, content_hash, doc_id
from evals.corpus.model import DocTypeSpec
from evals.corpus.mutators import applicable, clean_label, mutate

MANIFEST_VERSION = 1
BASES_PER_MUTATOR = 2
SHARED_DOC = "shared_02"  # the second example, with one value copied from the first
_MARKER = ".evals-build"


class BuildError(RuntimeError):
    """The build directory can't be used safely."""


def plan_cases(spec: DocTypeSpec) -> list[tuple[str, str, str | None]]:
    """(case id, base document, mutator or None) for every comply case of one pair.

    Every held-out document is a clean control. Each applicable mutator is applied to
    ``BASES_PER_MUTATOR`` bases, rotating through the held-out documents so each base carries
    a similar number of mutations.
    """
    held = [doc_id(i) for i in range(EXAMPLES, EXAMPLES + HELD_OUT)]
    cases: list[tuple[str, str, str | None]] = [(f"{spec.pair}/{h}/clean", h, None) for h in held]
    for k, name in enumerate(applicable(spec)):
        for j in range(BASES_PER_MUTATOR):
            base = held[(k * BASES_PER_MUTATOR + j) % HELD_OUT]
            cases.append((f"{spec.pair}/{base}/{name}", base, name))
    return cases


def truth_hash(truth: list[dict[str, Any]]) -> str:
    """sha256 of a document's ground truth as canonical JSON."""
    canonical = json.dumps(truth, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _hash_without(data: dict[str, Any], *keys: str) -> str:
    body = {key: value for key, value in data.items() if key not in keys}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def corpus_hash(manifest: dict[str, Any]) -> str:
    """sha256 of the manifest's canonical JSON without its own hash field and ``analyze``.

    The manifest holds every file's content hash, every ground-truth hash and every label, so
    this one value identifies the corpus that comply and generate use. The analyze-only
    material is identified by ``analyze_hash`` instead.
    """
    return _hash_without(manifest, "corpus_hash", "analyze")


def analyze_hash(section: dict[str, Any]) -> str:
    """sha256 of the manifest's ``analyze`` section without its own hash field."""
    return _hash_without(section, "analyze_hash")


def _document(pair: str, name: str, data: bytes, truth: list[dict[str, Any]],
              values: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": f"{pair}/{name}.docx",
        "content_hash": content_hash(data),
        "truth_hash": truth_hash(truth),
        "values": values,
    }


def shared_overrides(pair: str) -> dict[str, Any]:
    """The value the shared-value document of ``pair`` copies from the first example."""
    spec = ALL_SPECS[pair]
    key = next(block.key for block in spec.blocks if block.id == SHARED_FIELDS[pair])
    return {key: spec.values(0)[key]}


def build_shared(pair: str) -> tuple[bytes, list[dict[str, Any]]]:
    """The shared-value document of ``pair``: ``ex_02`` with one value taken from ``ex_01``."""
    return build_document(ALL_SPECS[pair], 1, shared_overrides(pair))


def _build_analyze(out_dir: Path) -> dict[str, Any]:
    """The analyze-only material, written to ``out_dir`` and described for the manifest.

    ``out_dir/<pair>/`` already holds the shared types' documents when this runs.
    """
    types: dict[str, Any] = {}
    for pair, spec in ANALYZE_SPECS.items():
        (out_dir / pair).mkdir(parents=True)
        documents: dict[str, Any] = {}
        for index in range(EXAMPLES):
            name = doc_id(index)
            data, truth = build_document(spec, index)
            (out_dir / pair / f"{name}.docx").write_bytes(data)
            documents[name] = _document(pair, name, data, truth, spec.values(index))
        types[pair] = {
            "doc_type": spec.doc_type,
            "lang": spec.lang,
            "examples": [doc_id(i) for i in range(EXAMPLES)],
            "documents": documents,
        }
    shared: dict[str, Any] = {}
    for pair in ALL_SPECS:
        data, truth = build_shared(pair)
        (out_dir / pair / f"{SHARED_DOC}.docx").write_bytes(data)
        values = {**ALL_SPECS[pair].values(1), **shared_overrides(pair)}
        shared[pair] = {"field": SHARED_FIELDS[pair], "copied_from": "ex_01", "base": "ex_02",
                        **_document(pair, SHARED_DOC, data, truth, values)}
    section: dict[str, Any] = {"types": types, "shared": shared}
    return {"analyze_hash": analyze_hash(section), **section}


def _prepare(out_dir: Path) -> None:
    if out_dir.exists() and any(out_dir.iterdir()):
        if not (out_dir / _MARKER).exists():
            raise BuildError(f"{out_dir} is not empty and was not made by `corpus build`")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / _MARKER).write_text("Built by `python -m evals corpus build`.\n")


def build_corpus(out_dir: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Build every file into ``out_dir``; write and return the manifest."""
    _prepare(out_dir)
    types: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    for pair, spec in SPECS.items():
        pair_dir = out_dir / pair
        (pair_dir / "cases").mkdir(parents=True)
        documents: dict[str, Any] = {}
        built: dict[str, tuple[bytes, list[dict[str, Any]]]] = {}
        for index in range(EXAMPLES + HELD_OUT):
            name = doc_id(index)
            data, truth = build_document(spec, index)
            built[name] = (data, truth)
            (pair_dir / f"{name}.docx").write_bytes(data)
            documents[name] = _document(pair, name, data, truth, spec.values(index))
        types[pair] = {
            "doc_type": spec.doc_type,
            "lang": spec.lang,
            "examples": [doc_id(i) for i in range(EXAMPLES)],
            "held_out": [doc_id(i) for i in range(EXAMPLES, EXAMPLES + HELD_OUT)],
            "documents": documents,
        }
        for case_id, base, mutator in plan_cases(spec):
            if mutator is None:
                label, file, digest = clean_label(), documents[base]["file"], None
            else:
                data, label = mutate(mutator, *built[base], spec)
                file = f"{pair}/cases/{base}__{mutator}.docx"
                (out_dir / file).write_bytes(data)
                digest = content_hash(data)
            cases.append(
                {
                    "id": case_id,
                    "pair": pair,
                    "base": base,
                    "file": file,
                    "content_hash": digest or documents[base]["content_hash"],
                    "label": label,
                }
            )
    manifest: dict[str, Any] = {"version": MANIFEST_VERSION, "types": types, "cases": cases}
    manifest = {"version": MANIFEST_VERSION, "corpus_hash": corpus_hash(manifest), **manifest,
                "analyze": _build_analyze(out_dir)}
    if manifest_path is not None:
        write_manifest(manifest, manifest_path)
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    """Write the manifest as stable, reviewable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(jsonfmt.dumps(manifest) + "\n", encoding="utf-8", newline="\n")


def load_manifest(path: Path) -> dict[str, Any]:
    """Read a manifest written by ``build_corpus``."""
    return json.loads(path.read_text(encoding="utf-8"))


def truth_for(pair: str, name: str) -> list[dict[str, Any]]:
    """The ground truth of document ``name`` of ``pair``, rebuilt from the generator."""
    from evals.corpus.generator import doc_index

    if name == SHARED_DOC:
        return build_shared(pair)[1]
    return build_document(ALL_SPECS[pair], doc_index(name))[1]


def select_cases(
    manifest: dict[str, Any], types: list[str] | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """The cases a run checks: the chosen types (all by default), at most ``limit`` per type."""
    selected: list[dict[str, Any]] = []
    for pair in manifest["types"]:
        if types and pair not in types:
            continue
        cases = [case for case in manifest["cases"] if case["pair"] == pair]
        selected.extend(cases[:limit] if limit else cases)
    return selected


def same_cases(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two manifests describe the same documents and cases, ignoring file bytes.

    True when every document's ground-truth hash and values, and every case's ID and label,
    match. A corpus built with another python-docx or lxml version can differ in packaging
    alone; its cases are still the same ones.
    """
    def documents(m: dict[str, Any]) -> dict[str, Any]:
        return {(pair, name): (doc["truth_hash"], doc["values"])
                for pair, name, doc in all_documents(m)}

    def cases(m: dict[str, Any]) -> list[Any]:
        return [(case["id"], case["base"], case["label"]) for case in m["cases"]]

    return documents(a) == documents(b) and cases(a) == cases(b)


def all_types(manifest: dict[str, Any]) -> dict[str, Any]:
    """Every type in the manifest: the shared ones, then the analyze-only ones."""
    return {**manifest["types"], **(manifest.get("analyze") or {}).get("types", {})}


def all_documents(manifest: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(pair, name, entry) for every clean document, shared-value documents included."""
    documents = [(pair, name, doc) for pair, info in all_types(manifest).items()
                 for name, doc in info["documents"].items()]
    shared = (manifest.get("analyze") or {}).get("shared", {})
    return documents + [(pair, SHARED_DOC, doc) for pair, doc in shared.items()]


def stale_files(manifest: dict[str, Any], build_dir: Path) -> list[str]:
    """Files the manifest names that are missing from ``build_dir`` or differ from it."""
    expected: dict[str, str] = {}
    for _pair, _name, document in all_documents(manifest):
        expected[document["file"]] = document["content_hash"]
    for case in manifest["cases"]:
        expected[case["file"]] = case["content_hash"]
    problems = []
    for file, digest in sorted(expected.items()):
        path = build_dir / file
        if not path.exists() or content_hash(path.read_bytes()) != digest:
            problems.append(file)
    return problems


def summary(manifest: dict[str, Any]) -> str:
    """One paragraph describing what was built."""
    cases = manifest["cases"]
    clean = sum(1 for case in cases if case["label"]["mutator"] == "none")
    documents = sum(len(info["documents"]) for info in manifest["types"].values())
    mutators = len({case["label"]["mutator"] for case in cases} - {"none"})
    analyze = manifest.get("analyze") or {"types": {}}
    extra = sum(len(info["documents"]) for info in analyze["types"].values()) + len(
        analyze.get("shared", {}))
    return (
        f"{len(manifest['types'])} types, {documents} documents, {len(cases)} comply cases "
        f"({clean} clean controls = {clean / len(cases):.0%}, {mutators} mutators). "
        f"Corpus hash {manifest['corpus_hash'][:12]}. Analyze only: "
        f"{len(analyze['types'])} more types, {extra} documents "
        f"(hash {analyze.get('analyze_hash', '')[:12]})."
    )
