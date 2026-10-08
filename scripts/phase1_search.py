"""scripts/phase1_search.py
Query DocuMind's Chroma vector store for nearest chunks to a question.
Usage: python scripts/phase1_search.py "<question>" --top-k 3
"""

from __future__ import annotations

import argparse
import sys
import time

from documind.core.config import load_settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.vector_store import ChromaStore


def main() -> None:
    t0_start = time.perf_counter()
    parser = argparse.ArgumentParser(
        description="Search indexed documents using nearest-neighbor query"
    )
    parser.add_argument("question", type=str, help="Search query question")
    parser.add_argument("--top-k", type=int, default=3, help="Number of nearest chunks to retrieve")
    args = parser.parse_args()

    settings = load_settings()
    store_dir = settings.home / "chroma"
    store = ChromaStore(store_dir, settings.embed_model, 384)
    embedder = SentenceTransformerEmbedder(model_id=settings.embed_model)

    query_vec = embedder.embed_query(args.question)
    hits = store.query(query_vec, top_k=args.top_k)

    if not hits:
        print("No matching documents found in index.")
        return

    for h in hits:
        snippet = h.chunk.text[:160].replace("\n", " ")
        header = f"[{h.rank}] score: {h.score:.3f} | {h.chunk.source}#{h.chunk.chunk_index}"
        print(f"{header} | {snippet}")

    elapsed_ms = (time.perf_counter() - t0_start) * 1000
    print(f"\nCompleted search in {elapsed_ms:.1f} ms", file=sys.stderr)


if __name__ == "__main__":
    main()
