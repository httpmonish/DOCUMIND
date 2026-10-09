# 0006. Concurrency and Threadpool Model

## Context
The DocuMind server exposes a REST API via FastAPI and Uvicorn. The underlying core uses embedded ChromaDB (`PersistentClient`), which relies on an embedded SQLite database and local HNSW graph files. Simultaneously, embedding models and LLM network calls are synchronous blocking CPU and I/O operations. We need a concurrency model that supports simultaneous read queries without corrupting embedded database files or overloading memory.

## Options
1. **Async Endpoints (`async def`) with Global Async Locks**:
   - Running endpoints as `async def` means code runs directly on the asyncio event loop.
   - Synchronous CPU-heavy embedding and blocking Anthropic network calls would block the event loop, causing severe latency spikes for concurrent healthchecks and queries.
   - Requires rewriting the core engine to be fully asynchronous or sprinkling `run_in_threadpool` throughout core methods.
2. **Multi-Worker Uvicorn Deployment (`--workers > 1`)**:
   - Multiple worker processes attempt concurrent writes to the same local Chroma SQLite database.
   - Chroma SQLite database locks and race conditions cause `database is locked` errors and graph index corruption.
   - Exposes CVE-2026-45829 if Chroma server mode were enabled.
3. **Plain `def` Endpoints in Threadpool with Write Serialization and Single Uvicorn Worker (Chosen)**:
   - Endpoints are declared as plain synchronous `def` functions. FastAPI automatically offloads them to its `anyio` worker threadpool, ensuring the event loop remains responsive.
   - Uvicorn runs with strictly one worker process (`workers=1`).
   - A single `threading.Lock` (`write_lock`) serializes mutating operations (`POST /v1/documents`, `DELETE /v1/documents`).
   - Read queries (`POST /v1/ask`) do not acquire the write lock, allowing concurrent read queries while ingestion occurs.
   - Core uses an internal `Semaphore(2)` around embedding encoding to prevent CPU/memory exhaustion on 8 GB laptops.

## Decision
Adopt Option 3. Declare all FastAPI route handlers as standard `def` rather than `async def`. Mandate single-worker Uvicorn execution (`uvicorn documind.interfaces.api:app --workers 1`). Protect all indexing and deletion writes behind a dedicated `threading.Lock`, while allowing read queries (`/v1/ask`) to execute concurrently in parallel worker threads without waiting for the write lock.

## You give up X to get Y
You give up multi-process horizontal CPU scaling on a single machine to get **corrupt-free embedded Chroma storage, non-blocking concurrent reads, safe and simple threadpool execution, and strict memory containment within 2.5 GB**.

## Revisit when
The system replaces embedded ChromaDB with an external, distributed, multi-writer vector database (such as Qdrant or Milvus).
