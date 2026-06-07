"""Classifier entry point: choose LLM when active, else heuristic; never crash."""

from __future__ import annotations

import logging

from ..ai.client import LLMCancelled, LLMClient, LLMError
from ..config import Settings
from ..schemas.classification import ClassificationResult
from ..schemas.diff import DiffRunResult
from ..schemas.extraction import DocumentExtraction
from .heuristic import classify_heuristic
from .llm import classify_llm

logger = logging.getLogger("docforge.ai_classifier")


def classify(
    extraction: DocumentExtraction,
    diff: DiffRunResult | None = None,
    *,
    client: LLMClient | None = None,
    settings: Settings | None = None,
    on_progress=None,
    cancel_event=None,
) -> ClassificationResult:
    """Classify a document. Uses the LLM if configured, with a heuristic fallback.

    ``on_progress(detail, fraction)`` (optional) receives live progress while the
    LLM streams its output. The fallback also covers the case where the LLM is
    reachable but returns unusable output — the platform must always produce a result.

    ``cancel_event`` (optional threading.Event) aborts the LLM call when set; the
    cancellation propagates (it is NOT swallowed by the heuristic fallback).
    """
    client = client or LLMClient()

    if client.active:
        try:
            return classify_llm(
                extraction, diff, client, on_progress=on_progress, cancel_event=cancel_event
            )
        except LLMCancelled:
            raise  # surfaced to the job runner, which marks the job cancelled
        except LLMError as exc:
            logger.warning("LLM classification failed, falling back to heuristic: %s", exc)
            result = classify_heuristic(extraction, diff)
            result.source = "heuristic_fallback"
            result.ai_warning = f"AI was skipped — used built-in heuristics instead. {exc}"
            return result

    return classify_heuristic(extraction, diff)
