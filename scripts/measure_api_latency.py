"""scripts/measure_api_latency.py
Measures end-to-end HTTP latency (p50, p95, min, max) for POST /v1/ask.
Can be executed with FakeLLM (default, ₹0) or live Anthropic Claude (--live).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from tests.engine_helpers import make_engine

BENCHMARK_KEY = "benchmark_key_32_characters_long_for_measurement_test"


def run_latency_benchmark(n_queries: int = 50, live: bool = False) -> None:
    settings = Settings(
        api_key=BENCHMARK_KEY,
        home=Path("/tmp"),
        rate_limit_per_min=10000,
    )
    eng, _, _ = make_engine(Path("/tmp"), NumpyStore(), fill=True)
    eng.settings = settings

    if live:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable required for --live benchmark")
        from documind.core.llm import ClaudeLLM

        eng.llm = ClaudeLLM(api_key=api_key)

    app = create_app(dm=eng, settings=settings)
    client = TestClient(app)
    headers = {"X-API-Key": BENCHMARK_KEY}

    # Warmup
    print("Warming up engine...")
    for _ in range(min(5, n_queries)):
        client.post("/v1/ask", json={"question": "what is a semaphore"}, headers=headers)

    print(f"Benchmarking {n_queries} queries...")
    latencies: list[float] = []
    for i in range(n_queries):
        t0 = time.perf_counter()
        resp = client.post("/v1/ask", json={"question": "what is a semaphore"}, headers=headers)
        if resp.status_code != 200:
            print(f"Query {i} returned status {resp.status_code}: {resp.text}")
            continue
        latencies.append((time.perf_counter() - t0) * 1000)

    if not latencies:
        print("Error: No successful queries completed.")
        return

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    min_lat = min(latencies)
    max_lat = max(latencies)

    label = "Claude 3.5 Haiku" if live else "FakeLLM"
    print(f"\n=== LATENCY BENCHMARK RESULTS ({label}) ===")
    print(f"Queries: {len(latencies)}")
    print(f"p50: {p50:.2f} ms")
    print(f"p95: {p95:.2f} ms")
    print(f"min: {min_lat:.2f} ms")
    print(f"max: {max_lat:.2f} ms")
    gate_status = "PASS" if p95 <= 8000 else "FAIL"
    print(f"NFR1 Gate (p95 <= 8000 ms): {gate_status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure DocuMind REST API latency")
    parser.add_argument("--n", type=int, default=50, help="Number of queries (default: 50)")
    parser.add_argument("--live", action="store_true", help="Use real Anthropic Claude model")
    args = parser.parse_args()
    run_latency_benchmark(n_queries=args.n, live=args.live)


if __name__ == "__main__":
    main()
