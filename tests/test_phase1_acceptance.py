"""tests/test_phase1_acceptance.py
Acceptance tests verifying end-to-end semantic retrieval with the real embedding model.
"""

from __future__ import annotations

import pytest

from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.types import Chunk
from tests.conftest import RealIndexHelper

pytestmark = pytest.mark.slow


def test_semaphore_question_retrieves_the_semaphore_chunk(real_index: RealIndexHelper) -> None:
    hits = real_index.search("what is a semaphore", top_k=3)
    assert len(hits) > 0
    assert "semaphore" in hits[0].chunk.text.lower()
    assert hits[0].score > 0.5


def test_no_chunk_exceeds_the_model_window(
    real_embedder: SentenceTransformerEmbedder, fixture_chunks: list[Chunk]
) -> None:
    assert len(fixture_chunks) > 0
    tokenizer = real_embedder.tokenizer
    lengths = [len(tokenizer(c.text)["input_ids"]) for c in fixture_chunks]
    assert max(lengths) <= 512
