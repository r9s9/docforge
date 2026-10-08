"""The AI layer's error vocabulary, shared by every transport.

Callers branch on these types rather than on provider-specific exceptions, so a
new transport only has to map its own failures onto them.
"""

from __future__ import annotations


class LLMError(Exception):
    """Raised when the model cannot be reached or cannot produce valid output."""


class LLMCancelled(LLMError):
    """Raised when an in-flight LLM call is aborted via its cancellation Event.

    Distinct from LLMError so callers can mark the job *cancelled* rather than
    silently fall back to heuristics (which would defeat the cancel).
    """


class LLMUnavailable(LLMError):
    """Raised when the model server is transiently overloaded (429/5xx) and
    retries were exhausted. Distinct from LLMError so callers can try a
    different model (e.g. reasoning tier -> workhorse) before giving up.
    """


class LLMRefused(LLMError):
    """The model declined the request on safety grounds (``stop_reason: refusal``).

    Retrying the same content gets the same answer, so callers treat it like any
    other AI failure (heuristic fallback) while the message tells the user why.
    """

    def __init__(self, category: str | None = None):
        self.category = category or ""
        what = f" ({self.category})" if self.category else ""
        super().__init__(
            f"Claude declined to process this content{what}. The built-in engine was used instead."
        )
