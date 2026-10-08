import numpy as np
import pytest

from documind.core.embedder import SentenceTransformerEmbedder
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
