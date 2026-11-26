"""Comply suite: check every case with DocForge's real ``check_document`` and ``fix_document``.

For each document type the runner first builds one **frozen template**:
1. Store the 5 examples.
2. Run ``analyze_documents`` with AI off.
3. Run ``publish_template``.

Every case of that type, in every mode, is then checked against that template, so modes differ
only in the step being measured. In AI runs, AI is switched off while the template is frozen.
This is the flow of ``backend/tests/integration/test_flows.py``. Nothing from the pipeline is
re-implemented here: the runner only records what DocForge returns.

``fix_document`` is deterministic, so fixes are measured in the no-AI run only.

Must be imported after ``evals.harness.prepare()`` has set up the sandbox.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from docforge.config import get_settings
from docforge.db.session import SessionLocal
from docforge.document_ingest import store_source_document
from docforge.services import analyze_documents, check_document, fix_document, publish_template
from docforge.template_registry import TemplateRegistry
from evals import scope
from evals.corpus.build import select_cases, truth_for
from evals.corpus.ground_truth import resolve, skeleton

_EXPECTED_CLASS = {"fixed": "FIXED", "auto": "AUTO_FIELD", "table": "REPEATABLE_TABLE"}


def _filename(case_or_doc_id: str) -> str:
    return case_or_doc_id.replace("/", "__") + ".docx"


@contextmanager
def ai_off():
    """Switch DocForge's AI off inside the block (the template is always frozen without AI)."""
    settings = get_settings()
    was = settings.ai_enabled
    settings.ai_enabled = False
    try:
        yield
    finally:
        settings.ai_enabled = was


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


def run(
    manifest: dict[str, Any],
    build_dir: Path,
    *,
    types: list[str] | None = None,
    limit: int | None = None,
    ai: bool = False,
    cache=None,
    observer=None,
    should_stop: Callable[[list[dict[str, Any]]], str | None] | None = None,
    repeat: int = 1,
    sample: int = 0,
    progress: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    """Check every selected case and return ``records``, ``templates``, ``repeats``, ``stopped``.

    With ``repeat`` > 1, ``sample`` judged cases are checked again ``repeat - 1`` times, each
    under its own cache key, to measure how stable the judge is.
    """
    db = SessionLocal()
    records: list[dict[str, Any]] = []
    templates: dict[str, Any] = {}
    frozen_by_pair: dict[str, dict[str, Any]] = {}
    repeats: list[dict[str, Any]] = []
    stopped: str | None = None
    selected = select_cases(manifest, types, limit)
    try:
        for index, case in enumerate(selected):
            pair = case["pair"]
            if pair not in frozen_by_pair:
                with ai_off():
                    frozen_by_pair[pair] = freeze_template(db, pair, manifest, build_dir)
                templates[pair] = {k: v for k, v in frozen_by_pair[pair].items()
                                   if k not in ("template", "node_to_logical")}
            record = _run_case(db, frozen_by_pair[pair], case, manifest, build_dir,
                               ai=ai, cache=cache, observer=observer)
            records.append(record)
            if progress:
                progress(record, index + 1, len(selected))
            if should_stop and (stopped := should_stop(records)):
                break
        if not stopped and repeat > 1 and sample > 0:
            stopped = _repeat_sample(db, records, frozen_by_pair, manifest, build_dir, repeats,
                                     ai=ai, cache=cache, observer=observer, repeat=repeat,
                                     sample=sample, should_stop=should_stop)
    finally:
        db.close()
    return {"records": records, "templates": templates, "repeats": repeats, "stopped": stopped}


def stability_sample(records: list[dict[str, Any]], sample: int) -> list[dict[str, Any]]:
    """A fixed choice of judged cases: the first ``sample`` by a hash of their ID."""
    judged = [r for r in records if (r.get("judge") or {}).get("status") == "ran"]
    return sorted(judged, key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())[:sample]


def _repeat_sample(db, records, frozen_by_pair, manifest, build_dir, repeats, *, ai, cache,
                   observer, repeat, sample, should_stop) -> str | None:
    cases = {case["id"]: case for case in manifest["cases"]}
    for k in range(1, repeat):
        for record in stability_sample(records, sample):
            again = _run_case(db, frozen_by_pair[record["pair"]], cases[record["id"]], manifest,
                              build_dir, ai=ai, cache=cache, observer=observer, repeat=k)
            repeats.append({
                "id": record["id"],
                "repeat": k,
                "error": again["error"],
                "judge": again.get("judge"),
                "semantic": (again.get("dimensions") or {}).get("semantic"),
                "verdicts": [d.get("verdict") for d in again.get("differences") or []],
                "spend_usd": again.get("spend_usd"),
                "check_ms": again.get("check_ms"),
            })
            if should_stop and (reason := should_stop(records + repeats)):
                return reason
    return None


def _judge_summary(record: dict[str, Any], observer, case_id: str, repeat: int,
                   ai: bool) -> dict[str, Any]:
    """Attach the judge's verdicts to the differences; say whether the judge ran."""
    differences = record["differences"]
    if not ai:
        return {"status": "off"}
    if not differences:
        return {"status": "not_needed"}
    judged = observer.verdicts(case_id, repeat) if observer else []
    by_index = {v["index"]: v for v in (judged[-1] if judged else [])}
    for index, difference in enumerate(differences):
        verdict = by_index.get(index)
        if verdict is not None:
            difference["verdict"] = {"material": bool(verdict.get("material")),
                                     "severity": verdict.get("severity")}
    status = "ran" if "semantic" in record["dimensions"] else "failed"
    return {
        "status": status,
        "judged": sum(1 for d in differences if "verdict" in d),
        "not_judged": sum(1 for d in differences if "verdict" not in d),
    }


def _run_case(db, frozen: dict[str, Any], case: dict[str, Any], manifest: dict[str, Any],
              build_dir: Path, *, ai: bool = False, cache=None, observer=None,
              repeat: int = 0) -> dict[str, Any]:
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
        with scope.case(case["id"], repeat):
            started = time.perf_counter()
            report = check_document(db, frozen["template"], filename=_filename(case["id"]),
                                    data=data)
            wall_ms = (time.perf_counter() - started) * 1000
        stats = cache.stats(case["id"], repeat) if cache else None
        # A replayed call reports the time it took when it was recorded.
        effective = wall_ms - stats.replay_ms + stats.recorded_ms if stats else wall_ms
        record["check_ms"] = round(effective, 1)
        record["wall_ms"] = round(wall_ms, 1)
        summary = _report_summary(report, frozen["node_to_logical"])
        values = summary.pop("field_values")  # only needed to judge a fix; not stored
        record.update(summary)
        record["judge"] = _judge_summary(record, observer, case["id"], repeat, ai)
        if ai:
            record["ai_calls"] = observer.calls(case["id"], repeat) if observer else []
            record["spend_usd"] = observer.spend(case["id"], repeat) if observer else None
            record["live_calls"] = stats.live_calls if stats else None
            record["replayed_calls"] = stats.replayed_calls if stats else None
            if report.token_usage:
                usage = report.token_usage
                record["tokens"] = {k: usage.get(k) for k in ("in", "out", "calls", "cost_usd")}
        elif case["label"]["fixable"]:
            # The fixer is deterministic, so it is measured in the no-AI run only.
            base_file = manifest["types"][case["pair"]]["documents"][case["base"]]["file"]
            record["fix"] = _fix(
                db, frozen["template"], case, data, values,
                (build_dir / base_file).read_bytes(), frozen["node_to_logical"],
            )
        if cache is not None:
            cache.mark_complete(case["id"], repeat)
    except Exception as exc:  # a failing case is a result, not a crash
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        record.setdefault("score", 0.0)
        record.setdefault("grade", "fail")
    return record
