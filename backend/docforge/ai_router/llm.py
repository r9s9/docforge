"""LLM-backed content router. Produces a RoutingResult identical in shape to the
heuristic path so callers don't care which engine ran.
"""

from __future__ import annotations

from ..ai.client import LLMClient
from ..ai.prompts import LLMRouteResponse, build_route_prompt
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition
from .naming import build_name_resolver

# Route this many fields per LLM call. Routing output is naturally bounded (the
# model only emits placements for content it actually found, not one per field),
# so it rarely needs splitting. We keep a high cap purely as a safety net for
# enormous templates — batching re-sends the whole document per call, which for
# the "From document" path is expensive, so we avoid it for normal templates.
ROUTE_BATCH_SIZE = 64


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


def route_llm(
    fields: list[FieldDefinition],
    *,
    raw_text: str | None,
    data: dict | None,
    client: LLMClient,
    template_id: str,
    version: int,
    from_document: bool = False,
    template_context: dict | None = None,
) -> RoutingResult:
    batches = _chunk(fields, ROUTE_BATCH_SIZE)
    valid = {f.field_name for f in fields}
    placements: list[PlacementInstruction] = []
    seen: set[str] = set()
    ambiguous: list[str] = []
    unmapped: list[str] = []

    for batch in batches:
        batch_valid = {f.field_name for f in batch}
        system, developer, user = build_route_prompt(
            batch,
            raw_text=raw_text,
            structured_data=data,
            from_document=from_document,
            template_context=template_context,
        )
        resp = client.complete_json(
            system=system, developer=developer, user=user, schema=LLMRouteResponse
        )
        resolve = build_name_resolver(batch)
        for p in resp.placements:
            # Accept a near-miss on the name (a dropped suffix, the label, a
            # tidied spelling) rather than discarding correct content because a
            # machine-made field name was not reproduced character for character.
            name = resolve(p.field_name)
            if name in batch_valid and name not in seen:
                seen.add(name)
                placements.append(
                    PlacementInstruction(
                        field_name=name,
                        value=p.value,
                        confidence=max(0.0, min(1.0, p.confidence)),
                        source_excerpt=p.source_excerpt,
                        ambiguous=p.ambiguous,
                        alternatives=p.alternatives,
                        note=p.note,
                    )
                )
        ambiguous.extend(a for a in resp.ambiguous_fields if a in valid)
        if len(batches) == 1:  # only meaningful when the model sees every field at once
            unmapped = resp.unmapped_content

    placed = {p.field_name for p in placements}
    missing = [f.field_name for f in fields if f.required and f.field_name not in placed]
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        ambiguous_fields=list(dict.fromkeys(ambiguous)),
        unmapped_content=unmapped,
        model_used=client.model,
        source="llm",
    )
