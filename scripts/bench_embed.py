"""scripts/bench_embed.py
Benchmark embedding throughput and peak RSS memory usage.
"""

from __future__ import annotations

import argparse
import resource
import sys
import time

from documind.core.embedder import SentenceTransformerEmbedder


def get_peak_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return usage.ru_maxrss / (1024 * 1024)
    return usage.ru_maxrss / 1024


def generate_synthetic_chunk(idx: int, words_count: int = 200) -> str:
    vocab = [
        "retrieval",
        "augmented",
        "generation",
        "vector",
        "database",
        "semantic",
        "search",
        "document",
        "chunking",
        "pipeline",
        "embedding",
        "transformer",
        "latency",
        "memory",
        "benchmark",
    ]
    words = [vocab[(idx * 7 + i) % len(vocab)] for i in range(words_count)]
    return " ".join(words)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark embedding throughput and peak RSS")
    parser.add_argument("--n", type=int, default=200, help="Number of synthetic chunks to embed")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size for embedding")
    args = parser.parse_args()

    print(f"Generating {args.n} synthetic 200-word chunks...")
    chunks = [generate_synthetic_chunk(i) for i in range(args.n)]

    print("Loading embedding model...")
    t0_load = time.perf_counter()
    embedder = SentenceTransformerEmbedder()
    load_time = time.perf_counter() - t0_load
    print(f"Model loaded in {load_time:.2f}s")

    print(f"Embedding {args.n} chunks (batch_size={args.batch_size})...")
    t0_embed = time.perf_counter()
    vectors = embedder.embed_documents(chunks, batch_size=args.batch_size)
    elapsed = time.perf_counter() - t0_embed

    chunks_per_sec = args.n / elapsed if elapsed > 0 else float("inf")
    peak_rss = get_peak_rss_mb()

    print("\n=== Benchmark Results ===")
    print(f"Total Chunks:      {args.n}")
    print(f"Elapsed Time:      {elapsed:.2f}s")
    print(f"Throughput:        {chunks_per_sec:.1f} chunks/s")
    print(f"Peak RSS:          {peak_rss:.1f} MB")
    print(f"Output shape:      {vectors.shape}")


if __name__ == "__main__":
    main()
