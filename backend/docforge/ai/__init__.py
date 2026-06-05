"""AI layer: OpenAI-compatible client + prompt templates."""

from __future__ import annotations

from .client import LLMClient, LLMError
from .prompts import (
    LLMClassifyResponse,
    LLMRouteResponse,
    build_classify_prompt,
    build_route_prompt,
)

__all__ = [
    "LLMClient",
    "LLMError",
    "build_classify_prompt",
    "build_route_prompt",
    "LLMClassifyResponse",
    "LLMRouteResponse",
]
