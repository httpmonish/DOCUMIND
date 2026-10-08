"""tests/conftest.py
Shared pytest fixtures for offline and real-model acceptance tests.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from documind.core.chunker import chunk_document
from documind.core.config import Settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.ingest import index_path
from documind.core.loader import load_document
from documind.core.types import Chunk, RetrievedChunk
from documind.core.vector_store import ChromaStore


class RealIndexHelper:
    def __init__(self, store: ChromaStore, embedder: SentenceTransformerEmbedder) -> None:
        self.store = store
        self.embedder = embedder

    def search(self, question: str, top_k: int = 3) -> list[RetrievedChunk]:
        vec = self.embedder.embed_query(question)
        return self.store.query(vec, top_k=top_k)


@pytest.fixture(scope="session")
def real_embedder() -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder()


@pytest.fixture(scope="session")
def fixture_chunks() -> list[Chunk]:
    fixtures_dir = Path("tests/fixtures")
    chunks: list[Chunk] = []
    settings = Settings()

    for f in sorted(fixtures_dir.glob("*")):
        if f.is_file() and f.suffix.lower() in {".pdf", ".txt", ".md"}:
            try:
                text = load_document(str(f))
            except Exception as err:
                logging.debug("Could not load fixture %s: %s", f, err)
                continue

            raw = chunk_document(
                {"text": text, "source": f.name},
                chunk_size=settings.chunk_size,
                overlap=settings.overlap,
            )
            for c in raw:
                chunks.append(
                    Chunk(
                        id=c["id"],
                        text=c["text"],
                        source=f.name,
                        chunk_index=c["chunk_index"],
                        doc_sha256="fixture-sha",
                    )
                )
    return chunks


@pytest.fixture
def real_index(tmp_path: Path, real_embedder: SentenceTransformerEmbedder) -> RealIndexHelper:
    store_dir = tmp_path / "chroma_acc"
    store = ChromaStore(store_dir, real_embedder.model_id, real_embedder.dim)
    fixtures_dir = Path("tests/fixtures")
    settings = Settings()

    index_path(fixtures_dir, fixtures_dir, real_embedder, store, settings)
    return RealIndexHelper(store, real_embedder)
