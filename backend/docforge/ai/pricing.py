"""Best-effort token cost estimates for the in-app usage/cost display.

Prices are USD per 1,000,000 tokens (input, output) and are inherently
approximate — providers change them and per-provider variants differ. They exist
only to show users a rough "~$0.004" figure next to each AI action; an unknown
model yields ``None`` (the UI shows the token counts without a dollar estimate).

Lookup is exact first, then the longest matching known prefix, so dated/preview
variants (e.g. ``gemini-2.5-flash-lite-preview-09-2025``) still resolve.
"""

from __future__ import annotations

# model-name (lowercased) -> (input_usd_per_1M, output_usd_per_1M), or for a
# model whose rate depends on prompt length, (input, output, long_input,
# long_output) with the split at LONG_PROMPT_TOKENS.
MODEL_PRICES: dict[str, tuple[float, ...]] = {
    # Anthropic Claude (recommended default: Haiku 5.5). Haiku 5.5 has two rate
    # cards chosen by the size of each request's prompt, so its cost has to be
    # computed per call (see cost_for_call), not from a model's token totals.
    "claude-haiku-5-5": (0.10, 0.50, 0.50, 2.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable-5": (10.00, 50.00),
    # NVIDIA Nemotron on OpenRouter (recommended default). OpenRouter model ids
    # carry the vendor prefix, which the prefix match below handles. Prices are
    # the cheapest endpoint OpenRouter routes to; a costlier upstream shifts the
    # estimate, which is why these figures are labelled approximate.
    "nvidia/nemotron-3-ultra": (0.50, 2.20),
    "nvidia/nemotron-3-super": (0.085, 0.40),
    "nvidia/nemotron-3.5-lightning": (0.08, 0.20),
    "nvidia/nemotron-3-nano": (0.02, 0.08),
    # Google Gemini — OpenAI-compatible endpoint
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    # Deprecated / shut down 2026-06-01 — kept only so historical usage logs from
    # before the shutdown still show a cost estimate; no longer offered in the UI.
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    # DeepSeek (OpenAI-compatible)
    "deepseek-v4-flash": (0.09, 0.18),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.14, 0.28),
    # OpenAI
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    # Anthropic, previous generation
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    # Zhipu GLM (OpenAI-compatible)
    "glm-4.6": (0.43, 1.74),
    "glm-4.5": (0.30, 1.10),
}


# Prompts above this many tokens move a two-card model to its long-prompt rate.
LONG_PROMPT_TOKENS = 100_000
# Anthropic prompt caching: reads cost a tenth of the input rate, 5-minute
# writes a quarter more than it.
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def _rates(model: str | None) -> tuple[float, ...] | None:
    if not model:
        return None
    key = model.strip().lower()
    if key in MODEL_PRICES:
        return MODEL_PRICES[key]
    # Longest known prefix wins (handles dated/preview suffixes).
    best: str | None = None
    for known in MODEL_PRICES:
        if key.startswith(known) and (best is None or len(known) > len(best)):
            best = known
    return MODEL_PRICES[best] if best else None


def price_for(model: str | None) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens for ``model`` at its standard (short-prompt) rate."""
    rates = _rates(model)
    return (rates[0], rates[1]) if rates else None


def cost_for_call(
    model: str | None,
    in_tokens: int,
    out_tokens: int,
    *,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float | None:
    """USD cost of one request, or None if the model is unpriced.

    ``in_tokens`` is the uncached part of the prompt; cache reads and writes are
    billed separately at their multipliers. The whole prompt (all three) decides
    which rate card applies.
    """
    rates = _rates(model)
    if rates is None:
        return None
    in_rate, out_rate = rates[0], rates[1]
    if len(rates) == 4 and in_tokens + cache_read + cache_write > LONG_PROMPT_TOKENS:
        in_rate, out_rate = rates[2], rates[3]
    total = (
        in_tokens * in_rate
        + cache_read * in_rate * CACHE_READ_MULTIPLIER
        + cache_write * in_rate * CACHE_WRITE_MULTIPLIER
        + out_tokens * out_rate
    )
    return total / 1_000_000


def estimate_cost(model: str | None, in_tokens: int, out_tokens: int) -> float | None:
    """USD cost of ``in_tokens``/``out_tokens`` on ``model``, or None if unknown."""
    cost = cost_for_call(model, in_tokens, out_tokens)
    return None if cost is None else round(cost, 6)


def cost_for_by_model(by_model: dict[str, dict]) -> float | None:
    """Sum estimated cost across a ``by_model`` usage map (see ai/usage.py).

    Returns None only when *no* model in the map has a known price; otherwise
    sums the known ones (unknown models contribute 0 to avoid hiding the total).
    """
    total = 0.0
    any_known = False
    for model, u in by_model.items():
        c = estimate_cost(model, int(u.get("in", 0)), int(u.get("out", 0)))
        if c is not None:
            any_known = True
            total += c
    return round(total, 6) if any_known else None
