"""Comply suite: check every case with DocForge's real ``check_document`` and ``fix_document``.

For each document type the runner first builds one **frozen template**:
1. Store the 5 examples.
2. Run ``analyze_documents`` with AI off.
3. Run ``publish_template``.

Every case of that type, in every mode, is then checked against that template, so modes differ
only in the step being measured. This is the flow of
``backend/tests/integration/test_flows.py``. Nothing from the pipeline is re-implemented here:
the runner only records what DocForge returns.

Must be imported after ``evals.harness.prepare()`` has set up the sandbox.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from docforge.config import get_settings
from docforge.db.session import SessionLocal
from docforge.document_ingest import store_source_document
from docforge.services import analyze_documents, check_document, fix_document, publish_template
from docforge.template_registry import TemplateRegistry
from evals.corpus.build import truth_for
from evals.corpus.ground_truth import resolve, skeleton

_EXPECTED_CLASS = {"fixed": "FIXED", "auto": "AUTO_FIELD", "table": "REPEATABLE_TABLE"}


def _filename(case_or_doc_id: str) -> str:
    return case_or_doc_id.replace("/", "__") + ".docx"


def freeze_template(db, pair: str, manifest: dict[str, Any], build_dir: Path) -> dict[str, Any]:
    """Analyze and publish one type's examples with AI off; map the result to ground truth."""
    settings = get_settings()
    registry = TemplateRegistry(settings.templates_dir)
    info = manifest["types"][pair]
    files = {
        name: (build_dir / info["documents"][name]["file"]).read_bytes()
        for name in info["examples"]
    }
    stored, names = [], {}
    for name, data in files.items():
        source = store_source_document(db, _filename(f"{pair}/{name}"), data)
        stored.append(source)
        names[source.id] = name
    started = time.perf_counter()
    job = analyze_documents(db, stored, settings=settings, name=pair)
    template, _version = publish_template(db, job, name=pair, settings=settings, registry=registry)
    seconds = time.perf_counter() - started

    representative = names[job.representative_document_id]
    truth = truth_for(pair, representative)
    logical_to_node = resolve(files[representative], truth)
    classes = {c["node_id"]: c["classification"] for c in job.classification["classifications"]}
    mismatches = []
    for element in truth:
        got = classes.get(logical_to_node[element["id"]], "none")
        want = _EXPECTED_CLASS.get(element["kind"], "DYNAMIC")
        if not (got == want or (want == "DYNAMIC" and got.startswith("DYNAMIC"))):
            mismatches.append(f"{element['id']}: {got}")
    return {
        "template": template,
        "node_to_logical": {node: logical for logical, node in logical_to_node.items()},
        "representative": representative,
        "fields": len(job.field_definitions or []),
        "classification_mismatches": mismatches,
        "seconds": round(seconds, 2),
    }


def _report_summary(report, node_to_logical: dict[str, str]) -> dict[str, Any]:
    return {
        "score": report.score,
        "grade": report.grade,
        "dimensions": {d.name: d.score for d in report.dimensions},
        "differences": [
            {
                "kind": d.kind,
                "severity": d.severity,
                "node_id": d.node_id,
                "logical_id": node_to_logical.get(d.node_id or ""),
                "field_name": d.field_name,
                "message": (d.message or "")[:160],
            }
            for d in report.differences
        ],
        "extras": [p.document_text for p in report.alignment if p.status == "extra"],
        "field_values": {
            p.node_id: p.document_text
            for p in report.alignment
            if p.status in ("field", "field_missing")
        },
    }


def _fix(db, template, case: dict[str, Any], data: bytes, values_before: dict[str, str],
         base: bytes, node_to_logical: dict[str, str]) -> dict[str, Any]:
    fixed, applied = fix_document(db, template, filename=_filename(case["id"]), data=data)
    recheck = _report_summary(
        check_document(db, template, filename=_filename(case["id"] + "/fixed"), data=fixed),
        node_to_logical,
    )
    targets = set(case["label"]["targets"])
    left = [d for d in recheck["differences"]
            if d["kind"] in ("changed_fixed", "missing_fixed") and d["logical_id"] in targets]
    fixed_skeleton, base_skeleton = skeleton(fixed), skeleton(base)
    return {
        "applied": applied,
        "recheck_clean": not left,
        "values_kept": recheck["field_values"] == values_before,
        "text_restored": [i[:3] for i in fixed_skeleton] == [i[:3] for i in base_skeleton],
        "style_restored": fixed_skeleton == base_skeleton,
        "recheck_score": recheck["score"],
    }


def run(manifest: dict[str, Any], build_dir: Path, *, types: list[str] | None = None,
        limit: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Check every selected case; return the case records and a summary of the templates."""
    db = SessionLocal()
    records: list[dict[str, Any]] = []
    templates: dict[str, Any] = {}
    try:
        for pair in manifest["types"]:
            if types and pair not in types:
                continue
            frozen = freeze_template(db, pair, manifest, build_dir)
            templates[pair] = {k: v for k, v in frozen.items()
                               if k not in ("template", "node_to_logical")}
            cases = [c for c in manifest["cases"] if c["pair"] == pair]
            for case in cases[:limit] if limit else cases:
                records.append(_run_case(db, frozen, case, manifest, build_dir))
    finally:
        db.close()
    return records, templates


def _run_case(db, frozen: dict[str, Any], case: dict[str, Any], manifest: dict[str, Any],
              build_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": case["id"],
        "pair": case["pair"],
        "base": case["base"],
        "mutator": case["label"]["mutator"],
        "label": case["label"],
        "error": None,
        "fix": None,
    }
    try:
        data = (build_dir / case["file"]).read_bytes()
        started = time.perf_counter()
        report = check_document(db, frozen["template"], filename=_filename(case["id"]), data=data)
        record["check_ms"] = round((time.perf_counter() - started) * 1000, 1)
        summary = _report_summary(report, frozen["node_to_logical"])
        values = summary.pop("field_values")  # only needed to judge a fix; not stored
        record.update(summary)
        if case["label"]["fixable"]:
            base_file = manifest["types"][case["pair"]]["documents"][case["base"]]["file"]
            record["fix"] = _fix(
                db, frozen["template"], case, data, values,
                (build_dir / base_file).read_bytes(), frozen["node_to_logical"],
            )
    except Exception as exc:  # a failing case is a result, not a crash
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        record.setdefault("score", 0.0)
        record.setdefault("grade", "fail")
    return record
