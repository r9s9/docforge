"""Route the *content of an uploaded document* onto a template's fields.

This powers "create a new doc from an existing filled DOCX": we extract all of
the source document's content (paragraphs + tables) and map it into the target
template's fields. The LLM does this best (it understands which paragraph is the
summary, which table is the line-items, etc.); a heuristic fallback handles
labeled lines and matches tables by header similarity.
"""

from __future__ import annotations

import logging

from ..ai.client import LLMClient, LLMError
from ..common.textutil import similarity
from ..schemas.enums import ElementType, FieldType
from ..schemas.extraction import DocumentExtraction
from ..schemas.routing import PlacementInstruction, RoutingResult
from ..schemas.template import FieldDefinition
from .llm import route_llm
from .router import route_unstructured_heuristic

logger = logging.getLogger("docforge.ai_router.document")


def document_content(doc: DocumentExtraction) -> dict:
    """Extract a routing-friendly view of a document: paragraphs + tables."""
    paragraphs: list[str] = []
    tables: list[dict] = []
    for e in doc.top_level_elements():
        if e.type == ElementType.TABLE and e.table_structure:
            ts = e.table_structure
            rows = ts.rows[1:] if len(ts.rows) > 1 else []
            tables.append({"headers": ts.headers, "rows": rows})
        elif e.text and e.text.strip():
            paragraphs.append(e.text.strip())
    return {"paragraphs": paragraphs, "tables": tables}


def extraction_blocks(doc: DocumentExtraction) -> list[dict]:
    """Ordered preview blocks (paragraphs/headings/tables) from an extraction —
    used to show users the content of an uploaded/checked document."""
    blocks: list[dict] = []
    for e in doc.top_level_elements():
        if e.type == ElementType.TABLE and e.table_structure:
            ts = e.table_structure
            blocks.append(
                {"type": "table", "headers": ts.headers, "rows": ts.rows[1:] if len(ts.rows) > 1 else []}
            )
        elif e.text and e.text.strip():
            kind = "heading" if e.type == ElementType.HEADING else "paragraph"
            blocks.append({"type": kind, "text": e.text, "style": e.style_name or ""})
    return blocks


def render_content_text(content: dict) -> str:
    """Readable flattening of document content for the unstructured LLM router."""
    lines = list(content.get("paragraphs", []))
    for t in content.get("tables", []):
        lines.append("TABLE:")
        lines.append(" | ".join(t.get("headers", [])))
        for r in t.get("rows", []):
            lines.append(" | ".join(r))
    return "\n".join(lines)


def _header_match(headers: list[str], labels: list[str]) -> float:
    return similarity(" | ".join(headers).lower(), " | ".join(labels).lower())


def _map_table_rows(table: dict, columns) -> list[dict]:
    """Map a content table's rows to column field_names (header-aware, positional fallback)."""
    headers = [h.lower() for h in table.get("headers", [])]
    col_to_idx: dict[str, int | None] = {}
    for col in columns:
        target = (col.label or col.field_name).lower()
        best_i, best_s = None, 0.0
        for i, h in enumerate(headers):
            s = similarity(h, target)
            if s > best_s:
                best_i, best_s = i, s
        col_to_idx[col.field_name] = best_i if best_s >= 0.5 else None

    out: list[dict] = []
    for r in table.get("rows", []):
        row: dict[str, str] = {}
        for ci, col in enumerate(columns):
            idx = col_to_idx.get(col.field_name)
            if idx is None:
                idx = ci
            row[col.field_name] = r[idx] if idx < len(r) else ""
        out.append(row)
    return out


def route_document_heuristic(
    fields: list[FieldDefinition], content: dict, template_id: str, version: int
) -> RoutingResult:
    # 1) Labeled lines + free-text prose via the standard unstructured router.
    base = route_unstructured_heuristic(
        fields, "\n".join(content.get("paragraphs", [])), template_id, version
    )
    placed = {p.field_name for p in base.placements}

    # 2) Map each unplaced table field to the best-matching content table.
    extra: list[PlacementInstruction] = []
    used: set[int] = set()
    table_fields = [f for f in fields if f.field_type == FieldType.TABLE and f.field_name not in placed]
    tables = content.get("tables", [])
    for tf in table_fields:
        labels = [c.label or c.field_name for c in tf.columns]
        best_i, best_s = -1, 0.0
        for i, t in enumerate(tables):
            if i in used:
                continue
            s = _header_match(t.get("headers", []), labels)
            if s > best_s:
                best_i, best_s = i, s
        if best_i >= 0 and best_s >= 0.3:
            used.add(best_i)
            extra.append(
                PlacementInstruction(
                    field_name=tf.field_name,
                    value=_map_table_rows(tables[best_i], tf.columns),
                    confidence=0.6,
                    source_excerpt="(table matched from document)",
                )
            )

    placements = base.placements + extra
    placed = {p.field_name for p in placements}
    missing = [f.field_name for f in fields if f.required and f.field_name not in placed]
    return RoutingResult(
        template_id=template_id,
        version=version,
        placements=placements,
        missing_required=missing,
        ambiguous_fields=base.ambiguous_fields,
        unmapped_content=base.unmapped_content,
        source="heuristic",
    )


def route_document_content(
    fields: list[FieldDefinition],
    content: dict,
    *,
    template_id: str,
    version: int,
    client: LLMClient | None = None,
) -> RoutingResult:
    """Map extracted document content onto template fields (LLM, heuristic fallback)."""
    from ..settings_store import interactive_ai_config

    client = client or LLMClient(interactive_ai_config())
    if client.active:
        try:
            return route_llm(
                fields,
                raw_text=render_content_text(content),
                data=None,
                client=client,
                template_id=template_id,
                version=version,
            )
        except LLMError as exc:
            logger.warning("LLM document routing failed, falling back to heuristic: %s", exc)
    return route_document_heuristic(fields, content, template_id, version)
