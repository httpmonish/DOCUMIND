#!/usr/bin/env python3
"""scripts/phase2_ask.py -- CLI tool for querying the DocuMind answer engine."""

from __future__ import annotations

import argparse
import sys

from documind.core.config import load_settings
from documind.core.factory import build_default
from documind.core.pricing import cost_usd
from documind.core.prompt import build_prompt


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask questions against DocuMind index.")
    parser.add_argument("question", help="User question to answer")
    parser.add_argument("--top-k", type=int, default=None, help="Number of retrieved chunks")
    parser.add_argument("--no-llm", action="store_true", help="Run retrieval-only mode")
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print system and user prompt and exit without calling LLM",
    )

    args = parser.parse_args()
    settings = load_settings()
    engine = build_default(settings)

    if args.no_llm:
        engine.llm = None

    if args.show_prompt:
        hits = engine.search(args.question, top_k=args.top_k)
        if not hits:
            print("No relevant chunks retrieved to build prompt.")
            sys.exit(3)
        prompt = build_prompt(args.question, hits)
        print("=== SYSTEM PROMPT ===")
        print(prompt.system)
        print("\n=== USER PROMPT ===")
        print(prompt.user)
        sys.exit(0)

    ans = engine.answer(args.question, top_k=args.top_k, interface="cli")

    print(f"Outcome: {ans.outcome}")
    if ans.abstain_reason:
        print(f"Reason:  {ans.abstain_reason}")
    print(f"\n{ans.text}\n")

    if ans.citations:
        print("Citations:")
        for c in ans.citations:
            print(f"  [{c.marker}] {c.source}#{c.chunk_index} (score: {c.score:.4f})")
            print(f'      "{c.snippet[:120]}..."\n')

    cost = cost_usd(ans.model, ans.usage)
    cost_str = f"${cost:.6f}" if cost is not None else "n/a"
    print(
        f"Latency: {ans.latency_ms} ms | Tokens: in={ans.usage.input_tokens}, "
        f"out={ans.usage.output_tokens} | Cost: {cost_str}"
    )

    if ans.outcome == "answered":
        sys.exit(0)
    else:
        sys.exit(3)


if __name__ == "__main__":
    main()
