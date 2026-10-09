"""tests/test_pipeline_integration.py -- Integration with ChromaStore and answer engine."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Sequence

import numpy as np

from documind.core.config import Settings
from documind.core.ingest import index_path
from documind.core.pipeline import DocuMind
from documind.core.vector_store import ChromaStore
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import FakeLLM


class IngestFakeEmbedder(FakeEmbedder):
    """Subclass of FakeEmbedder that captures indexed chunk text to simulate semantic matching."""

    def __init__(self) -> None:
        super().__init__()
        self.semaphore_chunk_text: str | None = None

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        for t in texts:
            if "semaphore" in t.lower() and self.semaphore_chunk_text is None:
                self.semaphore_chunk_text = t
        return super().embed_documents(list(texts))

    def embed_query(self, text: str) -> np.ndarray:
        if self.semaphore_chunk_text and "semaphore" in text.lower():
            return self._vec(self.semaphore_chunk_text)
        return super().embed_query(text)


def test_chroma_ingest_and_answer_pipeline(tmp_path: Path):
    home = tmp_path / "home"
    fixtures = Path(__file__).parent / "fixtures"
    os_file = fixtures / "os_notes.md"

    settings = dataclasses.replace(Settings(), home=home, min_score=0.1)
    embedder = IngestFakeEmbedder()
    store = ChromaStore(path=home / "chroma", model_slug="fake-embed", dim=embedder.dim)

    # Ingest document
    report = index_path(os_file, fixtures, embedder, store, settings)
    assert len(report.indexed) == 1
    assert report.chunks > 0

    # Answer question
    llm = FakeLLM("Semaphores synchronize threads by counting resources. [S1]")
    engine = DocuMind(settings, embedder, store, llm)

    ans = engine.answer("what is a semaphore?")
    assert ans.outcome == "answered"
    assert ans.abstain_reason is None
    assert len(ans.citations) == 1
    assert ans.citations[0].marker == "S1"
    assert ans.citations[0].source == "os_notes.md"
