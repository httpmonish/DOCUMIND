"""core/retrieval.py
Implements the Retriever class for semantic search with a confidence gate.
"""

from __future__ import annotations

from documind.core.types import Embedder, RetrievedChunk, VectorStore


class Retriever:
    """Retrieves relevant chunks from the vector store using semantic search."""

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        top_k: int = 5,
        tau: float = 0.45,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.top_k = top_k
        self.tau = tau

    def retrieve(self, question: str) -> tuple[list[RetrievedChunk], bool]:
        """
        Retrieve chunks relevant to the question.
        Returns a tuple of (retrieved_chunks, passed_gate).
        If the store is empty, returns ([], False) without embedding.
        The gate is passed if the top-1 chunk's score is >= tau.
        """
        if self.store.count() == 0:
            return [], False

        q_vec = self.embedder.embed_query(question)
        chunks = self.store.query(q_vec, self.top_k)

        # Ranks are 1-based (already set by VectorStore.query)
        passed_gate = len(chunks) > 0 and chunks[0].score >= self.tau

        return chunks, passed_gate
