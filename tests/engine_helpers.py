"""tests/engine_helpers.py -- shared builders for pipeline tests (no pytest fixtures needed)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Chunk, VectorStore
from tests.fake_embedder import FakeEmbedder
from tests.fake_llm import FakeLLM

SEMAPHORE_TEXT = "A semaphore is an integer counter used to control access to a shared resource."
PAGING_TEXT = "Paging divides memory into fixed-size frames and maps pages to frames."


class ScriptedEmbedder(FakeEmbedder):
    """embed_query returns the vector of a chosen chunk text, so retrieval is controlled.

    Questions not in `script` get an unrelated random vector
    (score ~ 0, i.e. below any sane threshold).
    """

    def __init__(self, script: dict[str, str]) -> None:
        super().__init__()
        self.script = script
        self.queries_embedded = 0

    def embed_query(self, text: str) -> np.ndarray:
        self.queries_embedded += 1
        return self._vec(self.script.get(text, "unrelated::" + text))


def make_engine(
    tmp_path: Path,
    store: VectorStore,
    *,
    reply: str | Exception = "A semaphore is a counter. [S1]",
    settings: Settings | None = None,
    extra_chunk_text: str | None = None,
    fill: bool = True,
) -> tuple[DocuMind, FakeLLM, ScriptedEmbedder]:
    """Returns (engine, llm, embedder). `store` is any VectorStore implementation."""
    emb = ScriptedEmbedder({"what is a semaphore": SEMAPHORE_TEXT})
    llm = FakeLLM(reply)
    cfg = settings or dataclasses.replace(Settings(), home=tmp_path)
    if fill:
        texts = [SEMAPHORE_TEXT, PAGING_TEXT] + ([extra_chunk_text] if extra_chunk_text else [])
        chunks = [
            Chunk(
                id=f"os.md_chunk_{i:04d}",
                text=t,
                source="os.md",
                chunk_index=i,
                doc_sha256="sha",
            )
            for i, t in enumerate(texts)
        ]
        store.upsert(chunks, emb.embed_documents([c.text for c in chunks]))
    return DocuMind(cfg, emb, store, llm), llm, emb
