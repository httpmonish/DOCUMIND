#!/usr/bin/env python3
"""scripts/smoke_llm.py -- One-call smoke test for Anthropic API."""

from __future__ import annotations

import os
import time

import anthropic
from dotenv import load_dotenv

from documind.core.pricing import cost_usd
from documind.core.types import Usage


def main() -> None:
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment or .env")
        return

    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("DOCUMIND_MODEL", "claude-haiku-4-5-20251001")

    t0 = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=20,
        messages=[{"role": "user", "content": "Say OK"}],
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    text = "".join(getattr(b, "text", "") for b in response.content)
    usage = Usage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    cost = cost_usd(model, usage)

    print(f"Reply:       {text.strip()}")
    print(f"Model:       {response.model}")
    print(f"Stop Reason: {response.stop_reason}")
    print(f"Usage:       in={usage.input_tokens}, out={usage.output_tokens}")
    print(f"Latency:     {latency_ms} ms")
    print(f"Cost:        ${cost:.6f}" if cost is not None else "Cost: Unknown")


if __name__ == "__main__":
    main()
