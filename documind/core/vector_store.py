"""documind/core/vector_store.py
Vector store implementations: in-memory NumpyStore and embedded ChromaStore.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np

from documind.core.errors import IndexUnavailable
from documind.core.types import SCHEMA_VERSION, Chunk, RetrievedChunk


class NumpyStore:
    """In-memory VectorStore using exact dot-product on L2-normalised vectors."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"Row-count mismatch: received {len(chunks)} chunks and {vectors.shape[0]} vectors."
            )

        if len(chunks) > 0 and vectors.shape[1] != self.dim:
            raise ValueError(
                f"Wrong dimension: expected vector dimension {self.dim}, got {vectors.shape[1]}."
            )

        for chunk, vec in zip(chunks, vectors, strict=True):
            self._chunks[chunk.id] = chunk
            self._vectors[chunk.id] = vec.astype(np.float32)

    def query(self, vector: np.ndarray, top_k: int) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")

        if vector.shape != (self.dim,):
            raise ValueError(f"Wrong dimension: expected shape ({self.dim},), got {vector.shape}")

        if not self._chunks:
            return []

        chunk_ids = list(self._chunks.keys())
        matrix = np.stack([self._vectors[cid] for cid in chunk_ids])

        # Vectors are L2 normalized, so cosine similarity equals dot product
        scores = matrix @ vector.astype(np.float32)

        k = min(top_k, len(chunk_ids))
        if k == len(chunk_ids):
            indices = np.argsort(-scores)
        else:
            partitioned = np.argpartition(-scores, k - 1)[:k]
            indices = partitioned[np.argsort(-scores[partitioned])]

        results: list[RetrievedChunk] = []
        for rank, idx in enumerate(indices, start=1):
            cid = chunk_ids[idx]
            results.append(
                RetrievedChunk(
                    chunk=self._chunks[cid],
                    score=float(scores[idx]),
                    rank=rank,
                )
            )
        return results

    def delete_source(self, source: str) -> int:
        ids_to_delete = [cid for cid, c in self._chunks.items() if c.source == source]
        for cid in ids_to_delete:
            del self._chunks[cid]
            del self._vectors[cid]
        return len(ids_to_delete)

    def count_for(self, source: str) -> int:
        return sum(1 for c in self._chunks.values() if c.source == source)

    def doc_sha(self, source: str) -> str | None:
        # Check chunk 0 only; if chunk 0 is missing, source is considered not indexed
        for c in self._chunks.values():
            if c.source == source and c.chunk_index == 0:
                return c.doc_sha256
        return None

    def sources(self) -> list[str]:
        return sorted({c.source for c in self._chunks.values()})

    def count(self) -> int:
        return len(self._chunks)


class ChromaStore:
    """ChromaDB embedded PersistentClient implementing VectorStore."""

    def __init__(self, path: Path, model_slug: str, dim: int = 384) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.path = Path(path)
        self.model_slug = model_slug
        self.dim = dim

        try:
            self.path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.path),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            coll_name = f"documind__{model_slug.replace('/', '_')}__s{SCHEMA_VERSION}"
            self._collection = self._client.get_or_create_collection(
                name=coll_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as err:
            msg = f"Failed to open or initialize Chroma index at {path}: {err}"
            raise IndexUnavailable(msg) from err

        self._check_and_write_metadata()

    def _check_and_write_metadata(self) -> None:
        meta_file = self.path / "meta.json"
        expected_meta = {
            "schema_version": SCHEMA_VERSION,
            "embed_model": self.model_slug,
        }

        if meta_file.exists():
            try:
                content = json.loads(meta_file.read_text(encoding="utf-8"))
                if content != expected_meta:
                    raise IndexUnavailable(
                        f"Existing index metadata mismatch at {meta_file}: "
                        f"found {content}, expected {expected_meta}"
                    )
            except IndexUnavailable:
                raise
            except Exception as err:
                raise IndexUnavailable(f"Corrupt meta.json at {meta_file}: {err}") from err
        else:
            try:
                meta_file.write_text(json.dumps(expected_meta, indent=2), encoding="utf-8")
            except Exception as err:
                raise IndexUnavailable(f"Failed to write metadata at {meta_file}: {err}") from err

    def upsert(self, chunks: Sequence[Chunk], vectors: np.ndarray) -> None:
        if len(chunks) != vectors.shape[0]:
            raise ValueError(
                f"Row-count mismatch: received {len(chunks)} chunks and {vectors.shape[0]} vectors."
            )

        if len(chunks) > 0 and vectors.shape[1] != self.dim:
            raise ValueError(
                f"Wrong dimension: expected dimension {self.dim}, got {vectors.shape[1]}."
            )

        if not chunks:
            return

        # Order chunk 0 last so interrupted writes remain invisible to doc_sha
        chunk_list = list(chunks)
        vec_list = [vectors[i].tolist() for i in range(len(chunks))]

        ordered_items = sorted(
            zip(chunk_list, vec_list, strict=True),
            key=lambda pair: 1 if pair[0].chunk_index == 0 else 0,
        )

        batch_size = 500
        for i in range(0, len(ordered_items), batch_size):
            batch = ordered_items[i : i + batch_size]
            ids = [c.id for c, _ in batch]
            documents = [c.text for c, _ in batch]
            embeddings = [v for _, v in batch]
            metadatas = [
                {
                    "source": c.source,
                    "chunk_index": c.chunk_index,
                    "doc_sha256": c.doc_sha256,
                    "embed_model": self.model_slug,
                    "schema_version": SCHEMA_VERSION,
                }
                for c, _ in batch
            ]
            try:
                self._collection.upsert(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=cast(Any, metadatas),
                )
            except Exception as err:
                raise IndexUnavailable(f"Chroma upsert failed: {err}") from err

    def query(self, vector: np.ndarray, top_k: int) -> list[RetrievedChunk]:
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")

        if vector.shape != (self.dim,):
            raise ValueError(f"Wrong dimension: expected ({self.dim},), got {vector.shape}")

        total_count = self.count()
        if total_count == 0:
            return []

        n_results = min(top_k, total_count)
        try:
            results = self._collection.query(
                query_embeddings=[vector.astype(np.float32).tolist()],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as err:
            raise IndexUnavailable(f"Chroma query failed: {err}") from err

        retrieved: list[RetrievedChunk] = []
        ids_batch = results.get("ids")
        docs_batch = results.get("documents")
        metas_batch = results.get("metadatas")
        dists_batch = results.get("distances")

        ids = ids_batch[0] if ids_batch is not None and len(ids_batch) > 0 else []
        docs = docs_batch[0] if docs_batch is not None and len(docs_batch) > 0 else []
        metas = metas_batch[0] if metas_batch is not None and len(metas_batch) > 0 else []
        dists = dists_batch[0] if dists_batch is not None and len(dists_batch) > 0 else []

        zipped = zip(ids, docs, metas, dists, strict=True)
        for rank, (cid, doc, meta, dist) in enumerate(zipped, start=1):
            chunk = Chunk(
                id=cid,
                text=str(doc),
                source=str(meta["source"]),
                chunk_index=int(str(meta["chunk_index"])),
                doc_sha256=str(meta["doc_sha256"]),
            )
            # Cosine distance to similarity: 1.0 - distance
            score = 1.0 - float(dist)
            retrieved.append(RetrievedChunk(chunk=chunk, score=score, rank=rank))

        return retrieved

    def delete_source(self, source: str) -> int:
        existing = self._collection.get(where={"source": source})
        ids = existing.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def count_for(self, source: str) -> int:
        existing = self._collection.get(where={"source": source})
        return len(existing.get("ids", []))

    def doc_sha(self, source: str) -> str | None:
        chunk_0_id = f"{source}_chunk_0000"
        res = self._collection.get(ids=[chunk_0_id], include=["metadatas"])
        metas = res.get("metadatas")
        if metas and len(metas) > 0 and metas[0]:
            return str(metas[0].get("doc_sha256"))
        return None

    def sources(self) -> list[str]:
        res = self._collection.get(include=["metadatas"])
        raw_metas = res.get("metadatas")
        metas = raw_metas if raw_metas is not None else []
        found: set[str] = set()
        for m in metas:
            if m and "source" in m:
                found.add(str(m["source"]))
        return sorted(found)

    def count(self) -> int:
        return int(self._collection.count())
