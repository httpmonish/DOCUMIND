"""scripts/token_stats.py
Calculates token length statistics for chunks across a document directory.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from documind.core.chunker import chunk_text
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.loader import load_document


def analyze_directory(dir_path: Path, embedder: SentenceTransformerEmbedder) -> None:
    valid_exts = {".pdf", ".txt", ".md"}
    files = sorted(p for p in dir_path.rglob("*") if p.is_file() and p.suffix.lower() in valid_exts)

    if not files:
        print(f"No .pdf, .txt, or .md files found in {dir_path}")
        return

    tokenizer = embedder.tokenizer
    token_counts: list[int] = []
    chunk_count = 0

    for file in files:
        try:
            text = load_document(str(file))
        except Exception as err:
            print(f"Skipping {file.name}: {err}", file=sys.stderr)
            continue

        chunks = chunk_text(text, chunk_size=200, overlap=30)
        chunk_count += len(chunks)

        for chunk in chunks:
            tokens = tokenizer(chunk)["input_ids"]
            token_counts.append(len(tokens))

    if not token_counts:
        print("No chunks produced.")
        return

    arr = np.array(token_counts)
    count = len(arr)
    p50 = np.percentile(arr, 50)
    p95 = np.percentile(arr, 95)
    p99 = np.percentile(arr, 99)
    max_val = np.max(arr)

    pct_above_256 = (np.sum(arr > 256) / count) * 100.0
    pct_above_512 = (np.sum(arr > 512) / count) * 100.0

    print("=== Token Statistics ===")
    print(f"Total chunks:      {count}")
    print(f"p50 tokens:        {p50:.1f}")
    print(f"p95 tokens:        {p95:.1f}")
    print(f"p99 tokens:        {p99:.1f}")
    print(f"Max tokens:        {max_val}")
    print(f"> 256 tokens:      {pct_above_256:.2f}%")
    print(f"> 512 tokens:      {pct_above_512:.2f}%")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze token lengths of chunks in a directory")
    parser.add_argument("path", type=str, help="Directory to analyze")
    args = parser.parse_args()

    target_dir = Path(args.path).resolve()
    if not target_dir.exists():
        print(f"Error: {target_dir} does not exist", file=sys.stderr)
        sys.exit(1)

    embedder = SentenceTransformerEmbedder()
    analyze_directory(target_dir, embedder)


if __name__ == "__main__":
    main()
