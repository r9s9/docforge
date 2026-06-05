"""ai_router — map structured/unstructured content onto template fields."""

from __future__ import annotations

from .document import document_content, extraction_blocks, route_document_content
from .router import route_structured, route_unstructured_heuristic
from .service import route

__all__ = [
    "route",
    "route_structured",
    "route_unstructured_heuristic",
    "route_document_content",
    "document_content",
    "extraction_blocks",
]
