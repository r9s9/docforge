"""LLM-backed content router. Produces a RoutingResult identical in shape to the
heuristic path so callers don't care which engine ran.
"""

from __future__ import annotations

from ..ai.client import LLMClient
from ..ai.prompts import LLMRouteResponse, build_route_prompt
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition


def route_llm(
    fields: list[FieldDefinition],
    *,
    raw_text: str | None,
    data: dict | None,
    client: LLMClient,
    template_id: str,
    version: int,
) -> RoutingResult:
    system, developer, user = build_route_prompt(fields, raw_text=raw_text, structured_data=data)
    resp = client.complete_json(
        system=system, developer=developer, user=user, schema=LLMRouteResponse
    )

    valid = {f.field_name for f in fields}
    placements = [
        PlacementInstruction(
            field_name=p.field_name,
            value=p.value,
            confidence=max(0.0, min(1.0, p.confidence)),
            source_excerpt=p.source_excerpt,
            ambiguous=p.ambiguous,
            alternatives=p.alternatives,
            note=p.note,
        )
        for p in resp.placements
        if p.field_name in valid
    ]
    placed = {p.field_name for p in placements}
    # Trust the model's missing list, but also backfill from required fields.
    missing = list(
        dict.fromkeys(
            list(resp.missing_required)
            + [f.field_name for f in fields if f.required and f.field_name not in placed]
        )
    )
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        ambiguous_fields=resp.ambiguous_fields,
        unmapped_content=resp.unmapped_content,
        model_used=client.model,
        source="llm",
    )
