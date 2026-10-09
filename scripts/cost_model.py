#!/usr/bin/env python3
"""scripts/cost_model.py -- Cost model for DocuMind RAG queries across Claude tiers."""

from __future__ import annotations


def calculate_query_cost(
    input_tokens: int,
    output_tokens: int,
    in_per_million: float,
    out_per_million: float,
) -> float:
    return (input_tokens * in_per_million + output_tokens * out_per_million) / 1_000_000.0


def main() -> None:
    # Baseline assumed token usage per RAG query:
    # 5 retrieved chunks * ~280 tokens + system prompt + question ~ 1,700 input tokens
    # Output answer ~ 300 tokens
    in_tok = 1700
    out_tok = 300

    # Pricing as of 2026-10-08 (USD per million tokens)
    haiku_in, haiku_out = 1.00, 5.00
    sonnet_in, sonnet_out = 2.00, 10.00

    haiku_cost = calculate_query_cost(in_tok, out_tok, haiku_in, haiku_out)
    sonnet_cost = calculate_query_cost(in_tok, out_tok, sonnet_in, sonnet_out)

    usd_inr = 86.50

    print("=== DocuMind Query Cost Model ===")
    print(f"Assumed tokens: {in_tok} in, {out_tok} out\n")

    print("Claude Haiku 4.5 ($1.00 / $5.00 per M tokens):")
    print(f"  Per query: ${haiku_cost:.6f}  (₹{haiku_cost * usd_inr:.3f})")
    print(f"  1,000 queries: ${haiku_cost * 1000:.2f} (₹{haiku_cost * 1000 * usd_inr:.1f})\n")

    print("Claude Sonnet 5.5 ($2.00 / $10.00 per M tokens):")
    print(f"  Per query: ${sonnet_cost:.6f}  (₹{sonnet_cost * usd_inr:.3f})")
    print(f"  1,000 queries: ${sonnet_cost * 1000:.2f} (₹{sonnet_cost * 1000 * usd_inr:.1f})\n")

    print(f"Ratio (Sonnet / Haiku): {sonnet_cost / haiku_cost:.1f}x")


if __name__ == "__main__":
    main()
