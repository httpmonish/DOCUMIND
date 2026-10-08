"""tests/test_vector_store_edges.py
Edge cases and error handling for NumpyStore and ChromaStore.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from documind.core.errors import IndexUnavailable
from documind.core.types import Chunk
from documind.core.vector_store import ChromaStore, NumpyStore


def test_numpy_store_empty_query() -> None:
    store = NumpyStore(dim=384)
    res = store.query(np.zeros(384, dtype=np.float32), top_k=5)
    assert res == []


def test_numpy_store_row_mismatch() -> None:
    store = NumpyStore(dim=384)
    chunks = [
        Chunk(id="c1", text="t1", source="s", chunk_index=0, doc_sha256="sha"),
    ]
    with pytest.raises(ValueError, match="Row-count mismatch"):
        store.upsert(chunks, np.zeros((2, 384), dtype=np.float32))


def test_chroma_store_corrupt_meta_json(tmp_path: Path) -> None:
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    meta = chroma_dir / "meta.json"
    meta.write_text("invalid json string {", encoding="utf-8")

    with pytest.raises(IndexUnavailable, match="Corrupt meta.json"):
        ChromaStore(chroma_dir, "bge-small-en-v1.5", 384)


def test_chroma_store_mismatched_meta_json(tmp_path: Path) -> None:
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    meta = chroma_dir / "meta.json"
    meta.write_text(
        json.dumps({"schema_version": 99, "embed_model": "other-model"}),
        encoding="utf-8",
    )

    with pytest.raises(IndexUnavailable, match="metadata mismatch"):
        ChromaStore(chroma_dir, "bge-small-en-v1.5", 384)
