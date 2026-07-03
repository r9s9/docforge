"""AI-authored field descriptions for tags-only mode.

``enforce_tags_only`` runs as a deterministic post-pass AFTER the classification
agent's self-critique already finished (see ``ai_classifier/llm.py``), so any
field it force-creates never got the model's attention — it only carries a
templated, content-citing placeholder description. This best-effort pass asks
the cheap workhorse model to write a real, specific description for exactly
those newly-forced fields, grounded in their original example text. A failure
here never breaks analysis: the deterministic description is kept as-is.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMCancelled, LLMClient, LLMError
from ..ai.prompts import LLMFieldDescriptions, build_describe_prompt
from ..schemas.classification import ClassificationResult
from ..schemas.extraction import DocumentExtraction
from ..settings_store import WORKHORSE_TIER

logger = logging.getLogger("docforge.ai_classifier")

# Kept small: this is a simple, cheap, high-volume task (unlike classification,
# which needs tools/evidence) so a modest batch keeps prompts fast and small.
_BATCH_SIZE = 30
_EXAMPLE_CHARS = 400


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def describe_forced_fields(
    client: LLMClient,
    extraction: DocumentExtraction,
    result: ClassificationResult,
    forced_node_ids: set[str],
    *,
    cancel_event=None,
    on_progress=None,
) -> int:
    """Overwrite the deterministic description with an AI-written one for every
    classification in ``forced_node_ids``. Returns how many were updated.

    A grouped repeatable section shares one field_name across several nodes —
    it is described ONCE and the result applied to every node in the group.
    """
    if not forced_node_ids or not client.active:
        return 0

    by_id = {e.node_id: e for e in extraction.elements}
    by_node = {c.node_id: c for c in result.classifications}

    # One request per unique field_name (grouped nodes share one field_name).
    seen_names: set[str] = set()
    items: list[dict] = []
    name_to_nodes: dict[str, list[str]] = {}
    for nid in forced_node_ids:
        c = by_node.get(nid)
        if c is None or not c.field_name:
            continue
        name_to_nodes.setdefault(c.field_name, []).append(nid)
        if c.field_name in seen_names:
            continue
        seen_names.add(c.field_name)
        el = by_id.get(nid)
        text = ((el.text if el else "") or "").strip()
        items.append(
            {
                "node_id": nid,
                "field_name": c.field_name,
                "field_type": c.field_type.value if c.field_type else "text",
                "classification": c.classification.value,
                "example_text": text[:_EXAMPLE_CHARS],
            }
        )

    if not items:
        return 0

    updated = 0
    tiered = client.for_tier(WORKHORSE_TIER)
    batches = _chunk(items, _BATCH_SIZE)
    n_batches = len(batches)
    for bi, batch in enumerate(batches):
        if cancel_event is not None and cancel_event.is_set():
            break
        if on_progress is not None:
            on_progress(
                f"AI writing field descriptions… batch {bi + 1}/{n_batches}",
                0.90 + 0.09 * bi / n_batches,
                "describe",
            )
        system, developer, user = build_describe_prompt(batch)
        try:
            resp = tiered.complete_json(
                system=system, developer=developer, user=user,
                schema=LLMFieldDescriptions, cancel_event=cancel_event,
            )
        except LLMCancelled:
            raise
        except LLMError:
            logger.debug(
                "field-description pass failed for a batch; keeping deterministic text",
                exc_info=True,
            )
            continue
        node_to_name = {it["node_id"]: it["field_name"] for it in batch}
        for d in resp.descriptions:
            desc = (d.description or "").strip()
            name = node_to_name.get(d.node_id)
            if not desc or not name:
                continue
            for nid in name_to_nodes.get(name, []):
                target = by_node.get(nid)
                if target is not None:
                    target.description = desc
                    updated += 1
    return updated
