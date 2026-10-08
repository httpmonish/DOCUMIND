"""documind/core/embedder.py
SentenceTransformer embedding wrapper implementing the Embedder protocol.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any

import numpy as np

from documind.core.errors import EmbeddingFailed

logger = logging.getLogger(__name__)

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
DEFAULT_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"

_ENCODE_SEMAPHORE = threading.Semaphore(2)


class SentenceTransformerEmbedder:
    """Wrapper around sentence-transformers using CPU and pinned BAAI/bge-small-en-v1.5."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        revision: str = DEFAULT_REVISION,
        device: str = "cpu",
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as err:
            raise ImportError("pip install 'documind[embed]'") from err

        self.model_id = model_id
        logger.info("Loading embedding model %s (revision: %s)", model_id, revision)

        try:
            self._model: Any = SentenceTransformer(
                model_id,
                device=device,
                trust_remote_code=False,
                revision=revision,
            )
        except Exception as err:
            raise EmbeddingFailed(f"Failed to load embedding model {model_id}: {err}") from err

        max_seq = getattr(self._model, "max_seq_length", None)
        if max_seq is None or max_seq < 512:
            raise ValueError(
                f"Model max_seq_length ({max_seq}) < 512. "
                "DocuMind requires at least 512 token context to avoid silent truncation."
            )

        dim_val = self._model.get_sentence_embedding_dimension()
        if dim_val is None:
            raise ValueError(f"Unable to determine embedding dimension for {model_id}")
        self.dim: int = int(dim_val)
        logger.info("Loaded model %s with embedding dimension %d", model_id, self.dim)

    @property
    def tokenizer(self) -> Any:
        return self._model.tokenizer

    def _encode_batch(self, batch: list[str]) -> np.ndarray:
        current_batch_size = len(batch)
        while current_batch_size >= 1:
            try:
                with _ENCODE_SEMAPHORE:
                    encoded = self._model.encode(
                        batch,
                        batch_size=current_batch_size,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                        convert_to_numpy=True,
                    )
                return np.asarray(encoded, dtype=np.float32)
            except (RuntimeError, MemoryError) as err:
                logger.warning(
                    "OOM or memory error with batch_size %d: %s. Retrying with halved batch size.",
                    current_batch_size,
                    err,
                )
                current_batch_size //= 2
                if current_batch_size < 1:
                    msg = f"Failed to encode batch even with batch_size=1: {err}"
                    raise EmbeddingFailed(msg) from err
            except Exception as err:
                raise EmbeddingFailed(f"Embedding failed: {err}") from err

        raise EmbeddingFailed("Failed to encode batch: batch size reduced below 1")

    def embed_documents(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        """float32, shape (len(texts), dim), L2-normalised rows."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        text_list = list(texts)
        results: list[np.ndarray] = []

        for i in range(0, len(text_list), batch_size):
            batch = text_list[i : i + batch_size]
            encoded = self._encode_batch(batch)
            results.append(encoded)

        return np.vstack(results).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """float32, shape (dim,), L2-normalised."""
        prefixed = f"{QUERY_PREFIX}{text}"
        with _ENCODE_SEMAPHORE:
            try:
                encoded = self._model.encode(
                    prefixed,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
            except Exception as err:
                raise EmbeddingFailed(f"Query embedding failed: {err}") from err

        vec = np.asarray(encoded, dtype=np.float32).flatten()
        return vec
