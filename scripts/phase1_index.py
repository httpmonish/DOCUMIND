"""scripts/phase1_index.py
Index documents in a path into DocuMind's Chroma vector store.
Usage: python scripts/phase1_index.py <path>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from documind.core.config import load_settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.ingest import index_path
from documind.core.vector_store import ChromaStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Index documents into DocuMind vector store")
    parser.add_argument("path", type=str, help="File or directory path to index")
    args = parser.parse_args()

    target_path = Path(args.path).resolve()
    if not target_path.exists():
        print(f"Error: path '{target_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    root = target_path.parent if target_path.is_file() else target_path

    settings = load_settings()
    store_dir = settings.home / "chroma"
    store = ChromaStore(store_dir, settings.embed_model, 384)
    embedder = SentenceTransformerEmbedder(model_id=settings.embed_model)

    report = index_path(target_path, root, embedder, store, settings)

    print(
        f"indexed {len(report.indexed)}, skipped {len(report.skipped)}, "
        f"failed {len(report.failed)}, chunks {report.chunks}"
    )

    if report.failed:
        for src, err in report.failed:
            print(f"  FAILED {src}: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
