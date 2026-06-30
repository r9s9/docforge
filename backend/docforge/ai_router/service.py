"""Routing entry point: structured is deterministic; unstructured prefers the LLM
(when configured) and falls back to heuristics. Never raises on LLM failure.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..config import Settings
from ..schemas.routing import RoutingResult
from ..schemas.template import FieldDefinition
from ..settings_store import generation_ai_config
from .compose import compose_values
from .llm import route_llm
from .router import route_structured, route_unstructured_heuristic

logger = logging.getLogger("docforge.ai_router")


def route(
    fields: list[FieldDefinition],
    *,
    template_id: str,
    version: int,
    raw_text: str | None = None,
    data: dict | None = None,
    client: LLMClient | None = None,
    settings: Settings | None = None,
) -> RoutingResult:
    client = client or LLMClient(generation_ai_config())

    # Pure structured input maps deterministically — no model needed.
    if data and not raw_text:
        return route_structured(fields, data, template_id, version)

    if client.active and (raw_text or data):
        try:
            routing = route_llm(
                fields,
                raw_text=raw_text,
                data=data,
                client=client,
                template_id=template_id,
                version=version,
            )
        except LLMError as exc:
            logger.warning("LLM routing failed, falling back to heuristic: %s", exc)
        except Exception:  # never let a routing hiccup 500 the request
            logger.exception("Unexpected error during LLM routing; using heuristic")
        else:
            # Compose: format/normalise values and draft missing required ones.
            return compose_values(
                routing, fields, source_text=raw_text or "", structured_data=data, client=client
            )

    return route_unstructured_heuristic(fields, raw_text or "", template_id, version)
