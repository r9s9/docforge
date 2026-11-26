"""Generate suite: fill each type's frozen template from rough notes with DocForge's real
``generate_document`` in ``unstructured_text`` mode (DESIGN.md §2.3), and record what it wrote.

Per notes case, inside the case's cache scope:
1. ``generate_document(db, template, GenerationInput(mode=UNSTRUCTURED_TEXT, raw_text=notes))``.
2. Read the ``GenerationRequest`` DocForge stored: the routing (which engine wrote the document,
   and each placement's ``ai_drafted`` flag), ``context_used`` (the values it rendered) and
   ``render_review`` (the read-back review's findings).
3. Read the output .docx from DocForge's storage and check its layout against the template's
   representative document.
4. Map each template field to its logical field through ``FieldDefinition.node_ids`` (the same
   mapping comply uses), and score it against the notes (``evals/metrics/generate.py``).
5. With a grader, grade each free-text field (``evals/graders/rubric.py``).

The template is frozen exactly as in comply: the examples analysed with AI off, then published.
Nothing from the pipeline is re-implemented here.

Must be imported after ``evals.harness.prepare()`` has set up the sandbox.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from docforge.config import get_settings
from docforge.db.models import GenerationRequest
from docforge.db.session import SessionLocal
from docforge.schemas.enums import GenerationMode
from docforge.schemas.generation import GenerationInput
from docforge.services import generate_document
from docforge.storage import get_storage
from docforge.template_registry import TemplateRegistry
from evals import scope
from evals.corpus.build import truth_for
from evals.corpus.doc_types import SPECS
from evals.corpus.ground_truth import skeleton
from evals.corpus.notes import NotesCase, field_kinds
from evals.metrics.generate import field_outcome, layout_problems, table_outcome
from evals.metrics.normalize import is_empty, is_placeholder, norm_text
from evals.runners.comply import ai_off, freeze_template

Grader = Callable[[NotesCase, str, str, list[str] | None], dict[str, Any]]
WRITER, REVIEW = "LLMWriteResponse", "LLMRenderReview"


def _freeze(db, pair: str, manifest: dict[str, Any], build_dir: Path) -> dict[str, Any]:
    frozen = freeze_template(db, pair, manifest, build_dir)
    template = frozen["template"]
    registry = TemplateRegistry(get_settings().templates_dir)
    fields = registry.load_fields(template.id, template.latest_version)
    representative = frozen["representative"]
    data = (build_dir / manifest["types"][pair]["documents"][representative]["file"]).read_bytes()
    return {**frozen, "fields": fields, "truth": truth_for(pair, representative),
            "skeleton": skeleton(data)}


def field_map(fields, node_to_logical: dict[str, str]) -> dict[str, str]:
    """Template field name → logical field ID, for fields that cover exactly one element."""
    mapping: dict[str, str] = {}
    for field in fields:
        logical = {node_to_logical.get(node) for node in field.node_ids} - {None}
        if len(logical) == 1:
            mapping[field.field_name] = logical.pop()
    return mapping


def table_rows(value: Any, field, headers: list[str]) -> list[list[Any]]:
    """A table field's value (a list of column-keyed dicts) as rows in the template's column
    order. A column is found by its label, else by its position."""
    order = []
    for position, header in enumerate(headers):
        by_label = next((c.field_name for c in field.columns
                         if norm_text(c.label) == norm_text(header)), None)
        by_position = field.columns[position].field_name if position < len(field.columns) else None
        order.append(by_label or by_position)
    rows = []
    for row in value if isinstance(value, list) else []:
        if isinstance(row, dict):
            rows.append([row.get(name) if name else None for name in order])
        elif isinstance(row, (list, tuple)):
            rows.append(list(row)[: len(headers)])
    return rows


def _scores(case: NotesCase, frozen: dict[str, Any], context: dict[str, Any],
            drafted: dict[str, bool]) -> tuple[dict, dict, dict, list[str]]:
    kinds = field_kinds(case.pair)
    lang = SPECS[case.pair].lang
    headers = {e["id"]: e["headers"] for e in frozen["truth"] if e["kind"] == "table"}
    mapping = field_map(frozen["fields"], frozen["node_to_logical"])
    by_logical = {logical: name for name, logical in mapping.items()}
    definitions = {f.field_name: f for f in frozen["fields"]}
    fields, tables, free, unmapped = {}, {}, {}, []
    for logical, expectation in case.expected.items():
        name = by_logical.get(logical)
        if name is None:
            unmapped.append(logical)
        value = context.get(name) if name else None
        kind = kinds[logical]
        if kind == "table":
            rows = table_rows(value, definitions[name], headers[logical]) if name else []
            tables[logical] = {**table_outcome(expectation, rows, case.text), "rows": rows}
        elif kind == "free":
            free[logical] = {"value": value, "points": expectation["points"], "grade": None}
        else:
            fields[logical] = field_outcome(
                kind, value, expectation, case.text, superseded=case.superseded.get(logical),
                ai_drafted=drafted.get(name, False), lang=lang,
            )
    return fields, tables, free, unmapped


def _grade(case: NotesCase, free: dict[str, Any], grader: Grader | None) -> dict[str, float]:
    spend = {"live": 0.0, "replayed": 0.0}
    for logical, item in free.items():
        value = item["value"]
        if is_empty(value) or is_placeholder(value):
            item["grade"] = {"status": "empty"}
        elif grader is None:
            item["grade"] = {"status": "off"}
        else:
            item["grade"] = grader(case, logical, str(value), item["points"])
            for key in spend:
                spend[key] += (item["grade"].get("spend_usd") or {}).get(key, 0.0)
    return spend


def _run_case(db, frozen: dict[str, Any], case: NotesCase, *, ai: bool, cache=None,
              observer=None, grader: Grader | None = None, repeat: int = 0) -> dict[str, Any]:
    record: dict[str, Any] = {"id": case.id, "pair": case.pair, "style": case.style,
                              "source": case.source, "ai": ai, "error": None}
    try:
        with scope.case(case.id, repeat):
            started = time.perf_counter()
            generated = generate_document(
                db, frozen["template"],
                GenerationInput(mode=GenerationMode.UNSTRUCTURED_TEXT, raw_text=case.text),
            )
            wall_ms = (time.perf_counter() - started) * 1000
            # DocForge's calls only: taken before grading, whose calls the cache counts too.
            stats = replace(cache.stats(case.id, repeat)) if cache else None
            request = db.get(GenerationRequest, generated.generation_request_id)
            routing = request.routing or {}
            context = request.context_used or {}
            drafted = {p["field_name"]: bool(p.get("ai_drafted"))
                       for p in routing.get("placements") or []}
            fields, tables, free, unmapped = _scores(case, frozen, context, drafted)
            grader_spend = _grade(case, free, grader)
        # A replayed call reports the time it took when it was recorded.
        record["generate_ms"] = round(
            wall_ms - stats.replay_ms + stats.recorded_ms if stats else wall_ms, 1)
        record["wall_ms"] = round(wall_ms, 1)
        calls = observer.calls(case.id, repeat) if observer else []
        kinds = Counter(call["kind"] for call in calls)
        review = routing.get("render_review") or []
        record.update({
            "routing": {
                "source": routing.get("source"),
                "model": routing.get("model_used"),
                "placements": len(routing.get("placements") or []),
                "missing_required": routing.get("missing_required") or [],
                "skipped_sections": len(routing.get("skipped_sections") or []),
                "unmapped_content": len(routing.get("unmapped_content") or []),
            },
            "review": {
                "ran": kinds[REVIEW] > 0,
                "findings": len(review),
                "correctable": sum(1 for f in review if f.get("severity") == "error"),
                "rewrite": kinds[WRITER] > 1,
            },
            "validation": {
                "status": (generated.validation or {}).get("status"),
                "issues": len((generated.validation or {}).get("issues") or []),
            },
            "fields": fields,
            "tables": tables,
            "free": free,
            "unmapped_fields": unmapped,
        })
        output = get_storage().get_bytes(generated.output_path)
        problems = layout_problems(frozen["truth"], frozen["skeleton"], skeleton(output))
        record["layout"] = {"preserved": not problems, "problems": problems}
        if grader is not None:
            record["grader_spend_usd"] = grader_spend
        if ai:
            record["ai_calls"] = calls
            record["spend_usd"] = observer.spend(case.id, repeat) if observer else None
            record["live_calls"] = stats.live_calls if stats else None
            record["replayed_calls"] = stats.replayed_calls if stats else None
            if request.token_usage:
                usage = request.token_usage
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
    cases: list[NotesCase],
    manifest: dict[str, Any],
    build_dir: Path,
    *,
    ai: bool = False,
    cache=None,
    observer=None,
    grader: Grader | None = None,
    should_stop: Callable[[list[dict[str, Any]]], str | None] | None = None,
    repeat: int = 1,
    sample: int = 0,
    progress: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    """Generate every case; return ``records``, ``templates``, ``repeats`` and ``stopped``."""
    db = SessionLocal()
    records: list[dict[str, Any]] = []
    repeats: list[dict[str, Any]] = []
    templates: dict[str, Any] = {}
    frozen: dict[str, dict[str, Any]] = {}
    stopped: str | None = None
    try:
        for index, case in enumerate(cases):
            if case.pair not in frozen:
                with ai_off():
                    frozen[case.pair] = _freeze(db, case.pair, manifest, build_dir)
                templates[case.pair] = {
                    k: v for k, v in frozen[case.pair].items()
                    if k not in ("template", "node_to_logical", "fields", "truth", "skeleton")
                }
                templates[case.pair]["template_fields"] = len(frozen[case.pair]["fields"])
            record = _run_case(db, frozen[case.pair], case, ai=ai, cache=cache,
                               observer=observer, grader=grader)
            records.append(record)
            if progress:
                progress(record, index + 1, len(cases))
            if should_stop and (stopped := should_stop(records)):
                break
        if not stopped and repeat > 1 and sample > 0:
            by_id = {case.id: case for case in cases}
            for k in range(1, repeat):
                for base in stability_sample(records, sample):
                    case = by_id[base["id"]]
                    again = _run_case(db, frozen[case.pair], case, ai=ai, cache=cache,
                                      observer=observer, grader=grader, repeat=k)
                    again["repeat"] = k
                    repeats.append(again)
                    if should_stop and (stopped := should_stop(records + repeats)):
                        break
                if stopped:
                    break
    finally:
        db.close()
    return {"records": records, "templates": templates, "repeats": repeats, "stopped": stopped}
