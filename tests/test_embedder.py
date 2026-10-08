from unittest.mock import MagicMock

import numpy as np
import pytest

from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.errors import EmbeddingFailed
from tests.fake_embedder import FakeEmbedder


def test_fake_embedder_deterministic():
    emb = FakeEmbedder()
    v1 = emb.embed_query("hello")
    v2 = emb.embed_query("hello")
    np.testing.assert_allclose(v1, v2)
    assert abs(float(np.linalg.norm(v1)) - 1.0) < 1e-5


def test_fake_embedder_empty_list():
    emb = FakeEmbedder()
    vecs = emb.embed_documents([])
    assert vecs.shape == (0, 384)


def test_embedder_context_length_too_small(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_model = MagicMock()
    mock_model.max_seq_length = 256
    mock_cls = MagicMock(return_value=mock_model)
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", mock_cls)

    with pytest.raises(ValueError, match="max_seq_length"):
        SentenceTransformerEmbedder()


def test_embedder_load_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_cls = MagicMock(side_effect=RuntimeError("Corrupt weights"))
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", mock_cls)

    with pytest.raises(EmbeddingFailed, match="Failed to load"):
        SentenceTransformerEmbedder()


def test_embedder_oom_fallback_and_query(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_model = MagicMock()
    mock_model.max_seq_length = 512
    mock_model.get_sentence_embedding_dimension.return_value = 384

    # Simulate OOM on batch size > 1, then success on batch size 1
    def mock_encode(batch: list[str], batch_size: int, **kwargs: object) -> np.ndarray:
        if batch_size > 1:
            raise RuntimeError("Out of memory")
        return np.ones((len(batch), 384), dtype=np.float32)

    mock_model.encode.side_effect = mock_encode
    mock_cls = MagicMock(return_value=mock_model)
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", mock_cls)

    embedder = SentenceTransformerEmbedder()
    docs = ["chunk1", "chunk2"]
    vecs = embedder.embed_documents(docs, batch_size=2)
    assert vecs.shape == (2, 384)

    # Test embed_query
    mock_model.encode.side_effect = lambda text, **kw: np.ones(384, dtype=np.float32)
    q_vec = embedder.embed_query("question")
    assert q_vec.shape == (384,)


@pytest.mark.slow
def test_real_embedder_properties():
    embedder = SentenceTransformerEmbedder()
    assert embedder.dim == 384
    assert embedder.model_id == "BAAI/bge-small-en-v1.5"

    # Empty list
    empty_vecs = embedder.embed_documents([])
    assert empty_vecs.shape == (0, 384)

    # Unit norms
    docs = [
        "A semaphore is a synchronization primitive used in concurrent programming.",
        "Paging is a memory management scheme that eliminates the need for contiguous allocation.",
    ]
    vecs = embedder.embed_documents(docs)
    assert vecs.shape == (2, 384)
    for row in vecs:
        norm = float(np.linalg.norm(row))
        assert abs(norm - 1.0) < 1e-3

    # Semantic relevance: query on semaphore is closer to semaphore doc than paging doc
    query_vec = embedder.embed_query("what is a semaphore")
    assert query_vec.shape == (384,)
    norm_q = float(np.linalg.norm(query_vec))
    assert abs(norm_q - 1.0) < 1e-3

    score_sem = float(np.dot(vecs[0], query_vec))
    score_page = float(np.dot(vecs[1], query_vec))
    assert score_sem > score_page
