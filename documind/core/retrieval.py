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
        tau: float = 0.35,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.top_k = top_k
        self.tau = tau

    def retrieve(self, question: str) -> tuple[list[RetrievedChunk], bool]:
        """Retrieve chunks relevant to the question.
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


def expand_neighbors(
    retrieved: list[RetrievedChunk],
    store: VectorStore,
    max_top_to_expand: int = 2,
) -> list[RetrievedChunk]:
    """Retrieve immediately adjacent chunks for the highest-ranking hits.
    Provides wider paragraph context around definition boundaries.
    """
    if not retrieved:
        return []

    seen_ids = {rc.chunk.id for rc in retrieved}
    expanded_list = list(retrieved)

    for rc in retrieved[:max_top_to_expand]:
        source_chunks = store.chunks_for(rc.chunk.source)
        by_index = {c.chunk_index: c for c in source_chunks}

        # Preceding chunk
        prev_chunk = by_index.get(rc.chunk.chunk_index - 1)
        if prev_chunk and prev_chunk.id not in seen_ids:
            seen_ids.add(prev_chunk.id)
            expanded_list.append(
                RetrievedChunk(
                    chunk=prev_chunk,
                    score=rc.score * 0.95,
                    rank=len(expanded_list) + 1,
                )
            )

        # Following chunk
        next_chunk = by_index.get(rc.chunk.chunk_index + 1)
        if next_chunk and next_chunk.id not in seen_ids:
            seen_ids.add(next_chunk.id)
            expanded_list.append(
                RetrievedChunk(
                    chunk=next_chunk,
                    score=rc.score * 0.95,
                    rank=len(expanded_list) + 1,
                )
            )

    return expanded_list
