"""documind/core/types.py
Data contracts shared by every component. Nothing in here does I/O.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import numpy as np

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Document:
    source: str  # POSIX path relative to the documents root, e.g. "os/unit3.pdf"
    text: str
    sha256: str  # hex digest of the raw file bytes


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str  # f"{source}_chunk_{chunk_index:04d}" (matches documind/core/chunker.py)
    text: str
    source: str
    chunk_index: int
    doc_sha256: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError(f"{self.id}: empty chunk text")
        if self.chunk_index < 0:
            raise ValueError(f"{self.id}: negative chunk_index")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: Chunk
    score: float  # cosine similarity in [-1, 1]; higher is closer
    rank: int  # 1-based


@dataclass(frozen=True, slots=True)
class Citation:
    marker: str  # "S1"
    source: str
    chunk_index: int
    snippet: str  # first 200 characters of the cited chunk
    score: float


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]
    outcome: Literal["answered", "abstained"]
    model: str
    usage: Usage
    latency_ms: int
    retrieved: tuple[RetrievedChunk, ...] = field(default=())
    abstain_reason: str | None = None


class Embedder(Protocol):
    model_id: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """float32, shape (len(texts), dim), L2-normalised rows."""
        ...

    def embed_query(self, text: str) -> np.ndarray:
        """float32, shape (dim,), L2-normalised."""
        ...


class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None: ...
    def query(self, vector: np.ndarray, top_k: int) -> list[RetrievedChunk]: ...
    def delete_source(self, source: str) -> int: ...
    def count_for(self, source: str) -> int: ...
    def doc_sha(self, source: str) -> str | None: ...
    def sources(self) -> list[str]: ...
    def count(self) -> int: ...
    def chunks_for(self, source: str) -> list[Chunk]: ...


class LLM(Protocol):
    model_id: str

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]: ...
