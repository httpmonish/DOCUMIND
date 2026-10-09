#!/usr/bin/env python3
"""scripts/phase2_calibrate.py -- Measure retrieval scores on on-topic vs off-topic questions."""

from __future__ import annotations

import statistics
from pathlib import Path

from documind.core.config import Settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.ingest import index_path
from documind.core.vector_store import NumpyStore


def main() -> None:
    fixtures = Path(__file__).parent.parent / "tests" / "fixtures"
    os_file = fixtures / "os_notes.md"
    on_topic_file = fixtures / "questions_on_topic.txt"
    off_topic_file = fixtures / "questions_off_topic.txt"

    settings = Settings(min_score=0.0)
    embedder = SentenceTransformerEmbedder()
    store = NumpyStore()

    print(f"Indexing {os_file}...")
    report = index_path(os_file, fixtures, embedder, store, settings)
    print(f"Indexed {report.chunks} chunks.")

    on_questions = [line.strip() for line in on_topic_file.read_text().splitlines() if line.strip()]
    off_questions = [
        line.strip() for line in off_topic_file.read_text().splitlines() if line.strip()
    ]

    print("\n--- ON-TOPIC QUESTIONS (top-1 score) ---")
    on_scores: list[float] = []
    for q in on_questions:
        q_vec = embedder.embed_query(q)
        hits = store.query(q_vec, top_k=1)
        score = hits[0].score if hits else 0.0
        on_scores.append(score)
        print(f"{score:.4f}  {q}")

    print("\n--- OFF-TOPIC QUESTIONS (top-1 score) ---")
    off_scores: list[float] = []
    for q in off_questions:
        q_vec = embedder.embed_query(q)
        hits = store.query(q_vec, top_k=1)
        score = hits[0].score if hits else 0.0
        off_scores.append(score)
        print(f"{score:.4f}  {q}")

    print("\n=== SUMMARY STATISTICS ===")
    print(
        f"On-Topic  (n={len(on_scores)}): min={min(on_scores):.4f}, "
        f"median={statistics.median(on_scores):.4f}, max={max(on_scores):.4f}"
    )
    print(
        f"Off-Topic (n={len(off_scores)}): min={min(off_scores):.4f}, "
        f"median={statistics.median(off_scores):.4f}, max={max(off_scores):.4f}"
    )


if __name__ == "__main__":
    main()
