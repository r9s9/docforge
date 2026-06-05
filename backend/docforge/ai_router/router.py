"""Heuristic content routing (deterministic, offline fallback).

Structured input is mapped key-by-key. Unstructured input is parsed line-by-line:
"Label: value" lines are matched to fields by name/label similarity; a single
remaining free-text field absorbs the leftover prose. Table fields are left to
the LLM router (heuristics can't reliably infer rows) and flagged if required.
"""

from __future__ import annotations

from typing import Any

from ..common.textutil import slugify_field
from ..schemas.enums import FieldType
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition


def _tokens(s: str) -> set[str]:
    return {t for t in slugify_field(s, fallback="").split("_") if t}


def _match_field(fields: list[FieldDefinition], key: str, label: str) -> FieldDefinition | None:
    best: FieldDefinition | None = None
    best_score = 0.0
    key_tokens = _tokens(key) or _tokens(label)
    for f in fields:
        if f.field_name == key:
            return f
        score = 0.0
        if slugify_field(f.label) == key:
            score = 0.9
        else:
            ft = _tokens(f.field_name) | _tokens(f.label)
            if key_tokens and ft:
                overlap = len(key_tokens & ft) / len(key_tokens | ft)
                score = overlap
        if score > best_score:
            best, best_score = f, score
    return best if best_score >= 0.5 else None


def route_structured(
    fields: list[FieldDefinition], data: dict[str, Any], template_id: str, version: int
) -> RoutingResult:
    placements: list[PlacementInstruction] = []
    field_names = {f.field_name for f in fields}
    for f in fields:
        if f.field_name in data and data[f.field_name] is not None:
            placements.append(
                PlacementInstruction(
                    field_name=f.field_name,
                    value=data[f.field_name],
                    confidence=1.0,
                    source_excerpt="(structured input)",
                )
            )
    placed = {p.field_name for p in placements}
    missing = [f.field_name for f in fields if f.required and f.field_name not in placed]
    unmapped = [f"unknown key: {k}" for k in data if k not in field_names]
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        unmapped_content=unmapped,
        source="structured",
    )


def route_unstructured_heuristic(
    fields: list[FieldDefinition], raw_text: str, template_id: str, version: int
) -> RoutingResult:
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    placements: list[PlacementInstruction] = []
    assigned: set[str] = set()
    leftovers: list[str] = []

    for line in lines:
        matched = False
        if ":" in line:
            label, _, value = line.partition(":")
            value = value.strip()
            field = _match_field(fields, slugify_field(label), label)
            if (
                field is not None
                and field.field_name not in assigned
                and field.field_type != FieldType.TABLE
                and value
            ):
                placements.append(
                    PlacementInstruction(
                        field_name=field.field_name,
                        value=value,
                        confidence=0.7,
                        source_excerpt=line,
                    )
                )
                assigned.add(field.field_name)
                matched = True
        if not matched:
            leftovers.append(line)

    # Assign the leftover prose to a remaining free-text field, if any.
    remaining_text = [
        f
        for f in fields
        if f.field_name not in assigned and f.field_type in (FieldType.TEXT, FieldType.MULTILINE_TEXT)
    ]
    # Drop all-caps title-ish lines from the leftover prose (reduces boilerplate
    # noise when mapping a whole document's content into one free-text field).
    prose = [ln for ln in leftovers if not (ln.isupper() and len(ln) < 60)]
    if prose and remaining_text:
        target = remaining_text[0]
        placements.append(
            PlacementInstruction(
                field_name=target.field_name,
                value=" ".join(prose),
                confidence=0.4,
                source_excerpt=prose[0][:80],
                ambiguous=len(remaining_text) > 1,
                alternatives=[f.field_name for f in remaining_text[1:]],
                note="Low-confidence: leftover text assigned to a free-text field.",
            )
        )
        assigned.add(target.field_name)
        leftovers = []

    missing = [f.field_name for f in fields if f.required and f.field_name not in assigned]
    ambiguous = [p.field_name for p in placements if p.ambiguous]
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        ambiguous_fields=ambiguous,
        unmapped_content=leftovers,
        source="heuristic",
    )
