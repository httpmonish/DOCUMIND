"""documind/core/pricing.py
Token pricing tables and query cost calculation.
"""

from __future__ import annotations

from documind.core.types import Usage

# VERIFY: https://platform.claude.com/docs/en/about-claude/pricing (dated 2026-10-08)
# Rates in USD per million tokens: (input_price_per_million, output_price_per_million)
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}


def cost_usd(model: str, usage: Usage) -> float | None:
    """Calculate total cost in USD for a model call.

    Returns None for unknown models so callers can record null instead of misleading 0.
    """
    price = PRICES.get(model)
    if price is None:
        return None
    in_per_m, out_per_m = price
    return (usage.input_tokens * in_per_m + usage.output_tokens * out_per_m) / 1_000_000.0
