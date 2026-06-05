"""ai_classifier — classify elements (FIXED/DYNAMIC/REPEATABLE/AUTO) and derive
field definitions + validation rules. Heuristic by default, LLM when configured.
"""

from __future__ import annotations

from .fields import derive_field_definitions, derive_validation_rules
from .heuristic import classify_heuristic
from .llm import classify_llm
from .service import classify

__all__ = [
    "classify",
    "classify_heuristic",
    "classify_llm",
    "derive_field_definitions",
    "derive_validation_rules",
]
