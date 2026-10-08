"""tests/store_contract.py
Behaviour EVERY VectorStore must satisfy (NumpyStore and ChromaStore).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from documind.core.types import Chunk
from tests.fake_embedder import FakeEmbedder

EMB = FakeEmbedder()


def make_chunks(source: str, n: int, sha: str = "sha-a", text: str = "text") -> list[Chunk]:
    return [
        Chunk(
            id=f"{source}_chunk_{i:04d}",
            text=f"{text} {source} {i}",
            source=source,
            chunk_index=i,
            doc_sha256=sha,
        )
        for i in range(n)
    ]


def vectors_for(chunks: list[Chunk]) -> np.ndarray:
    return EMB.embed_documents([c.text for c in chunks])


def orthogonal_to(v: np.ndarray) -> np.ndarray:
    r = EMB.embed_query("some unrelated probe text")
    w = r - float(r @ v) * v
    return (w / np.linalg.norm(w)).astype(np.float32)


def check_empty(store: Any) -> None:
    assert store.count() == 0
    assert store.sources() == []
    assert store.query(EMB.embed_query("anything"), top_k=5) == []
    assert store.doc_sha("nope.md") is None


def check_exact_match_is_top1_with_score_one(store: Any) -> None:
    chunks = make_chunks("a.md", 6)
    vecs = vectors_for(chunks)
    store.upsert(chunks, vecs)
    assert store.count() == 6 and store.count_for("a.md") == 6
    hits = store.query(vecs[3], top_k=3)
    assert [h.rank for h in hits] == [1, 2, 3]
    assert hits[0].chunk.id == "a.md_chunk_0003"
    assert hits[0].score >= 0.999
    assert hits[0].chunk.text == chunks[3].text and hits[0].chunk.doc_sha256 == "sha-a"
    assert all(hits[i].score >= hits[i + 1].score for i in range(2))
    assert len(store.query(vecs[0], top_k=50)) == 6  # top_k > count -> everything, no error


def check_score_is_cosine_not_l2(store: Any) -> None:
    chunks = make_chunks("a.md", 1)
    vecs = vectors_for(chunks)
    store.upsert(chunks, vecs)
    hit = store.query(orthogonal_to(vecs[0]), top_k=1)[0]
    assert abs(hit.score) < 0.01, f"orthogonal vectors must score ~0 (cosine); got {hit.score}"


def check_upsert_is_idempotent_and_updates(store: Any) -> None:
    chunks = make_chunks("a.md", 3)
    store.upsert(chunks, vectors_for(chunks))
    new = make_chunks("a.md", 3, sha="sha-b", text="edited")
    store.upsert(new, vectors_for(new))
    assert store.count() == 3
    hit = store.query(vectors_for(new)[1], top_k=1)[0]
    assert hit.chunk.text == new[1].text and hit.chunk.doc_sha256 == "sha-b"


def check_delete_source(store: Any) -> None:
    a, b = make_chunks("a.md", 4), make_chunks("b.md", 2)
    store.upsert(a, vectors_for(a))
    store.upsert(b, vectors_for(b))
    assert store.sources() == ["a.md", "b.md"]
    assert store.delete_source("a.md") == 4
    assert store.delete_source("a.md") == 0
    assert store.sources() == ["b.md"] and store.count() == 2


def check_doc_sha_and_partial_write_invisible(store: Any) -> None:
    chunks = make_chunks("a.md", 3, sha="sha-z")
    store.upsert(chunks, vectors_for(chunks))
    assert store.doc_sha("a.md") == "sha-z"
    assert store.doc_sha("missing.md") is None
    # simulate a crash that lost chunk 0: the source must look "not indexed"
    rest = chunks[1:]
    store.delete_source("a.md")
    store.upsert(rest, vectors_for(rest))
    assert store.doc_sha("a.md") is None


def check_bad_inputs_raise_valueerror(store: Any) -> None:
    chunks = make_chunks("a.md", 2)
    try:
        store.upsert(chunks, vectors_for(chunks)[:1])
    except ValueError:
        pass
    else:
        raise AssertionError("row-count mismatch must raise ValueError")
    store.upsert(chunks, vectors_for(chunks))
    try:
        store.query(np.ones(7, dtype=np.float32), top_k=1)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong dimension must raise ValueError")
    try:
        store.query(EMB.embed_query("q"), top_k=0)
    except ValueError:
        pass
    else:
        raise AssertionError("top_k < 1 must raise ValueError")


ALL_CHECKS = [
    check_empty,
    check_exact_match_is_top1_with_score_one,
    check_score_is_cosine_not_l2,
    check_upsert_is_idempotent_and_updates,
    check_delete_source,
    check_doc_sha_and_partial_write_invisible,
    check_bad_inputs_raise_valueerror,
]
