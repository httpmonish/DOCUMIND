# 0002. Vector Store Architecture

## Context
Indexed document chunks and dense embeddings must be persisted locally and searched using nearest-neighbor similarity. The store must support fast querying, metadata filtering, idempotent updates, and atomic source deletions.

## Options with numbers
1. **ChromaDB Client-Server (`chroma run` / `HttpClient`)**:
   - Requires running a separate server process.
   - Known security vulnerabilities (e.g. CVE-2026-45829 unauthenticated remote execution).
   - Introduces IPC / HTTP serialization latency on every query (~5–15 ms).
2. **FAISS (CPU)**:
   - Extremely fast C++ vector search.
   - Lacks built-in persistent metadata mapping; requires building manual SQLite/JSON metadata synchronizers.
3. **ChromaDB Embedded `PersistentClient` + `NumpyStore`** (Chosen):
   - Embedded `PersistentClient` runs in-process with zero network sockets or daemons.
   - Storage overhead for fixtures: **644 KB**.
   - Dual implementation: `NumpyStore` for fast deterministic memory testing, `ChromaStore` for persistence.
   - Distance space configured to **cosine** (`score = 1.0 - distance`).

## Decision
Use ChromaDB's embedded `PersistentClient` (`anonymized_telemetry=False`) behind an abstract `VectorStore` protocol. Forbid `HttpClient` and `chroma run`. Verify behavior using store contract tests against both `NumpyStore` and `ChromaStore`.

## You give up X to get Y
You give up concurrent multi-process writes to get **zero daemon management, zero network attack surface, and fully embedded local persistence**.

## Revisit when
Index sizes grow past 200,000 chunks or multi-tenant remote indexing becomes a required feature.
