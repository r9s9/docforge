"""Best-effort token cost estimates for the in-app usage/cost display.

Prices are USD per 1,000,000 tokens (input, output) and are inherently
approximate — providers change them and per-provider variants differ. They exist
only to show users a rough "~$0.004" figure next to each AI action; an unknown
model yields ``None`` (the UI shows the token counts without a dollar estimate).

Lookup is exact first, then the longest matching known prefix, so dated/preview
variants (e.g. ``gemini-2.5-flash-lite-preview-09-2025``) still resolve.
"""

from __future__ import annotations

# model-name (lowercased) -> (input_usd_per_1M, output_usd_per_1M)
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # Google Gemini (recommended default) — OpenAI-compatible endpoint
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-3-flash": (0.50, 3.00),
    "gemini-3-pro": (2.00, 12.00),
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
    # Anthropic
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    # Zhipu GLM (OpenAI-compatible)
    "glm-4.6": (0.43, 1.74),
    "glm-4.5": (0.30, 1.10),
}


def price_for(model: str | None) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens for ``model``, or None if unknown."""
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


def estimate_cost(model: str | None, in_tokens: int, out_tokens: int) -> float | None:
    """USD cost of ``in_tokens``/``out_tokens`` on ``model``, or None if unknown."""
    price = price_for(model)
    if price is None:
        return None
    in_rate, out_rate = price
    return round((in_tokens * in_rate + out_tokens * out_rate) / 1_000_000, 6)


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
