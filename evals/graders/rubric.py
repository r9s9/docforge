"""Rubric grader for free-text fields (DESIGN.md §6.5).

Exact matching can't score a services description or a meeting's decisions: a good value may
rephrase, shorten or translate the notes. For those fields, Claude Haiku 5.5 answers two
questions:
- **faithful**: is every claim in the value supported by the notes? (unsupported claims are
  listed)
- **complete**: does the value cover every expected point? (missing points are listed; not
  asked when the notes give nothing for the field)

The grader runs in the eval process, through the Anthropic SDK that DocForge already installs,
and never through DocForge. Its HTTP requests go through the response cache like DocForge's (the
SDK's ``httpx2`` transport), so a rerun replays them. Its cost, from DocForge's price table, is
reported apart from the mode's own cost. Its grades are used only where they agree with the
owner's labels (``evals/graders/labels.py``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from evals.corpus.doc_types import SPECS
from evals.corpus.notes import NotesCase

SYSTEM = (
    "You grade one field of a business document that was filled in from a user's rough notes. "
    "You check two things and nothing else.\n"
    "1. Faithful: every claim in the value is supported by the notes. The value may rephrase, "
    "shorten, reorder or translate what the notes say, but it must not add facts, numbers, "
    "dates, names, obligations or details that the notes don't contain. Generic connecting "
    "words are fine.\n"
    "2. Complete: the value covers every expected point, in any wording or language.\n"
    "Formatting, tone and spelling don't matter. Judge only the value you are given."
)


class RubricVerdict(BaseModel):
    """The grader's answer for one field."""

    unsupported_claims: list[str] = Field(
        default_factory=list, description="Claims in the value that the notes don't support")
    faithful: bool = Field(description="True if the value has no unsupported claims")
    missing_points: list[str] = Field(
        default_factory=list, description="Expected points the value doesn't cover")
    complete: bool = Field(description="True if the value covers every expected point")


def load_grader_config(path: Path) -> dict[str, Any]:
    """Read the grader's config file."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def field_name(logical: str) -> str:
    """``text.services`` → ``services``, ``field.purpose`` → ``purpose``."""
    return logical.split(".", 1)[-1].replace("_", " ")


def prompt(case: NotesCase, logical: str, value: str, points: list[str] | None) -> str:
    """The user message for one field."""
    spec = SPECS[case.pair]
    language = {"en": "English", "de": "German"}.get(spec.lang, spec.lang)
    expected = ("\n".join(f"- {point}" for point in points) if points
                else "(The notes give nothing for this field. Only judge faithfulness; answer "
                     "complete = true.)")
    return (
        f"Document type: {spec.doc_type.replace('_', ' ')}, written in {language}.\n"
        f"Field: {field_name(logical)}\n\n"
        f"<notes>\n{case.text.strip()}\n</notes>\n\n"
        f"<expected_points>\n{expected}\n</expected_points>\n\n"
        f"<value>\n{value.strip()}\n</value>\n\n"
        "List the claims in the value that the notes don't support, and the expected points the "
        "value misses. Leave a list empty when there are none."
    )


class Grader:
    """Grades free-text fields with Claude; callable as the generate runner's ``grader``."""

    def __init__(self, config: dict[str, Any], *, cache=None, client=None):
        self.config = config
        self.model = config["model"]
        self.cache = cache
        self._client = client
        self.spent = {"live": 0.0, "replayed": 0.0}

    @staticmethod
    def available(config: dict[str, Any]) -> bool:
        """Whether the key the config names is set (its value is never read here)."""
        return bool(os.environ.get(config.get("api_key_env", ""), "").strip())

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=os.environ[self.config["api_key_env"]], max_retries=2)
        return self._client

    def __call__(self, case: NotesCase, logical: str, value: str,
                 points: list[str] | None) -> dict[str, Any]:
        import anthropic

        from docforge.ai.pricing import cost_for_call

        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=int(self.config.get("max_tokens", 4000)),
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt(case, logical, value, points)}],
                output_config={"effort": self.config.get("effort", "medium")},
                output_format=RubricVerdict,
            )
        except anthropic.APIError as exc:
            return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        usage = response.usage
        cost = cost_for_call(
            self.model, usage.input_tokens, usage.output_tokens,
            cache_read=usage.cache_read_input_tokens or 0,
            cache_write=usage.cache_creation_input_tokens or 0,
        ) or 0.0
        live = self.cache.last_call_live() if self.cache is not None else True
        spend = {"live": cost if live else 0.0, "replayed": 0.0 if live else cost}
        for key in spend:
            self.spent[key] += spend[key]
        verdict = response.parsed_output
        if verdict is None:  # a refusal or a cut-off answer
            return {"status": "failed", "error": f"no verdict (stop: {response.stop_reason})",
                    "spend_usd": spend}
        return {
            "status": "graded",
            "faithful": verdict.faithful and not verdict.unsupported_claims,
            "unsupported_claims": verdict.unsupported_claims,
            "complete": (verdict.complete and not verdict.missing_points) if points else None,
            "missing_points": verdict.missing_points if points else [],
            "model": self.model,
            "tokens": {"in": usage.input_tokens, "out": usage.output_tokens},
            "spend_usd": spend,
        }
