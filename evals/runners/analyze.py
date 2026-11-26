"""Analyze suite: build a template from the first k examples of a type with DocForge's real
``analyze_documents`` and ``publish_template`` (DESIGN.md §2.3, §5.3), and score what it made of
each element of the example it took as its representative.

Per case, inside the case's cache scope:
1. Store the case's documents (``store_source_document``) in a fixed order.
2. ``analyze_documents(db, stored, mode="smart")``, then ``publish_template``.
3. Look up the representative DocForge chose (``job.representative_document_id``), rebuild its
   ground truth, and resolve every element, information-block cells included, to its node.
4. Read each node's classification (``job.classification``) and the field definition that covers
   it (``job.field_definitions``: its type, a table's columns), and score them
   (``evals/metrics/analyze.py``).
5. Read the published ``template.docx`` and check its layout against the representative.

The cases: for each type, its first 1, 2, 3 and 5 examples, then the shared-value pair (the
first example and ``shared_02``, which copies one value from it). Every case builds its own
template; nothing is frozen. Nothing from the pipeline is re-implemented here.

Must be imported after ``evals.harness.prepare()`` has set up the sandbox.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from docforge.config import get_settings
from docforge.db.session import SessionLocal
from docforge.document_ingest import store_source_document
from docforge.services.analysis import analyze_documents
from docforge.services.publish import publish_template
from docforge.template_registry import TemplateRegistry
from evals import scope
from evals.corpus.analyze import AnalyzeCase, document_file
from evals.corpus.build import truth_for
from evals.corpus.ground_truth import resolve, skeleton
from evals.metrics.analyze import case_outcomes, template_layout


def predictions(job, node_ids: dict[str, str]) -> dict[str, dict[str, Any]]:
    """What DocForge made of each logical element's node: classification, type, columns."""
    classes = {c["node_id"]: c for c in (job.classification or {}).get("classifications", [])}
    definitions: dict[str, dict[str, Any]] = {}
    for definition in job.field_definitions or []:
        for node in definition.get("node_ids") or []:
            definitions.setdefault(node, definition)
    out: dict[str, dict[str, Any]] = {}
    for logical, node in node_ids.items():
        cls = classes.get(node) or {}
        definition = definitions.get(node) or {}
        columns = [c.get("label") or "" for c in definition.get("columns") or []]
        out[logical] = {
            "class": cls.get("classification"),
            "field_type": definition.get("field_type") or cls.get("field_type"),
            "columns": columns or None,
        }
    return out


def _filename(case: AnalyzeCase, name: str) -> str:
    return f"{case.id.replace('/', '__')}__{name}.docx"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage()[:300])


@contextmanager
def collected_warnings() -> Iterator[list[str]]:
    """DocForge's warnings during a case, kept for its record instead of the console.

    They say why DocForge did something: a section it couldn't hide ("skipping section toggle"),
    or an AI step that fell back to the heuristic.
    """
    logger = logging.getLogger("docforge")
    collector, propagate = _Collector(), logger.propagate
    logger.addHandler(collector)
    logger.propagate = False
    try:
        yield collector.messages
    finally:
        logger.removeHandler(collector)
        logger.propagate = propagate


def _run_case(db, case: AnalyzeCase, manifest: dict[str, Any], build_dir: Path, *, ai: bool,
              cache=None, observer=None, repeat: int = 0) -> dict[str, Any]:
    record: dict[str, Any] = {"id": case.id, "pair": case.pair, "lang": case.lang, "k": case.k,
                              "group": case.group, "documents": list(case.documents),
                              "ai": ai, "error": None}
    if case.shared_field:
        record["shared_field"] = case.shared_field
    try:
        settings = get_settings()
        registry = TemplateRegistry(settings.templates_dir)
        files = {name: (build_dir / document_file(manifest, case.pair, name)).read_bytes()
                 for name in case.documents}
        with scope.case(case.id, repeat), collected_warnings() as warnings:
            stored, names = [], {}
            for name in case.documents:
                source = store_source_document(db, _filename(case, name), files[name])
                stored.append(source)
                names[source.id] = name
            started = time.perf_counter()
            job = analyze_documents(db, stored, settings=settings, name=case.id)
            analyzed = time.perf_counter()
            template, _version = publish_template(db, job, name=case.id, settings=settings,
                                                  registry=registry)
            published = time.perf_counter()
            stats = replace(cache.stats(case.id, repeat)) if cache else None
        wall_ms = (analyzed - started) * 1000
        # A replayed call reports the time it took when it was recorded.
        record["analyze_ms"] = round(
            wall_ms - stats.replay_ms + stats.recorded_ms if stats else wall_ms, 1)
        record["wall_ms"] = round(wall_ms, 1)
        record["publish_ms"] = round((published - analyzed) * 1000, 1)
        representative = names[job.representative_document_id]
        truth = truth_for(case.pair, representative)
        source = files[representative]
        outcomes = case_outcomes(truth, predictions(job, resolve(source, truth)))
        built = registry.template_docx_bytes(template.id, template.latest_version)
        problems = template_layout(truth, skeleton(source), skeleton(built), outcomes)
        classification = job.classification or {}
        record.update({
            "representative": representative,
            "source": classification.get("source"),
            "model": classification.get("model_used"),
            "ai_warning": job.ai_warning,
            "document_type_guess": job.document_type_guess,
            "fields": len(job.field_definitions or []),
            "warnings": list(dict.fromkeys(warnings)),
            "outcomes": outcomes,
            "layout": {"preserved": not problems, "problems": problems},
        })
        if ai:
            record["ai_calls"] = observer.calls(case.id, repeat) if observer else []
            record["spend_usd"] = observer.spend(case.id, repeat) if observer else None
            record["live_calls"] = stats.live_calls if stats else None
            record["replayed_calls"] = stats.replayed_calls if stats else None
            if job.token_usage:
                usage = job.token_usage
                record["tokens"] = {k: usage.get(k) for k in ("in", "out", "calls", "cost_usd")}
        if cache is not None:
            cache.mark_complete(case.id, repeat)
    except Exception as exc:  # a failing case is a result, not a crash
        record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return record


def stability_sample(records: list[dict[str, Any]], sample: int) -> list[dict[str, Any]]:
    """A fixed choice of cases: the first ``sample`` by a hash of their ID."""
    done = [r for r in records if not r.get("error")]
    return sorted(done, key=lambda r: hashlib.sha256(r["id"].encode()).hexdigest())[:sample]


def run(
    cases: list[AnalyzeCase],
    manifest: dict[str, Any],
    build_dir: Path,
    *,
    ai: bool = False,
    cache=None,
    observer=None,
    should_stop: Callable[[list[dict[str, Any]]], str | None] | None = None,
    repeat: int = 1,
    sample: int = 0,
    progress: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    """Analyze every case; return ``records``, ``templates``, ``repeats`` and ``stopped``."""
    db = SessionLocal()
    records: list[dict[str, Any]] = []
    repeats: list[dict[str, Any]] = []
    stopped: str | None = None
    try:
        for index, case in enumerate(cases):
            record = _run_case(db, case, manifest, build_dir, ai=ai, cache=cache,
                               observer=observer)
            records.append(record)
            if progress:
                progress(record, index + 1, len(cases))
            if should_stop and (stopped := should_stop(records)):
                break
        if not stopped and repeat > 1 and sample > 0:
            by_id = {case.id: case for case in cases}
            for k in range(1, repeat):
                for base in stability_sample(records, sample):
                    again = _run_case(db, by_id[base["id"]], manifest, build_dir, ai=ai,
                                      cache=cache, observer=observer, repeat=k)
                    again["repeat"] = k
                    repeats.append(again)
                    if should_stop and (stopped := should_stop(records + repeats)):
                        break
                if stopped:
                    break
    finally:
        db.close()
    templates: dict[str, Any] = {}
    for record in records:
        info = templates.setdefault(record["pair"], {"cases": [], "representatives": {}})
        info["cases"].append(record["id"])
        info["representatives"][record["id"]] = record.get("representative")
    return {"records": records, "templates": templates, "repeats": repeats, "stopped": stopped}
