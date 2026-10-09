# DocuMind Known Limitations & Architectural Boundaries

This document records the architectural limitations, performance boundaries, and operational constraints of DocuMind as of Phase 5.

---

## 1. Synchronous Upload and Indexing Pipeline
- **Limitation:** Ingestion (`POST /v1/documents`) executes synchronously within the request lifecycle. Document extraction, chunking, and dense vector embedding must complete before the HTTP 201 response is returned.
- **Timing & Latency:**
  - A 500-page PDF generates approximately 1,500 chunks (`chunk_size=200`, `overlap=30`).
  - **Estimated:** On a 4-core CPU laptop with 8 GB RAM and no GPU, embedding 1,500 chunks via `bge-small-en-v1.5` takes approximately **25–60 seconds**, plus 3–8 seconds for isolated PDF text extraction.
  - **Operational Requirement:** API clients uploading large documents must configure an HTTP request timeout of at least **90–120 seconds**.
- **Scope Boundary:** An asynchronous background job queue (e.g. Celery, RQ) and task polling endpoints are explicitly out of scope for v1.0.

---

## 2. Single-Worker Uvicorn Requirement
- **Limitation:** The Uvicorn server must be executed with strictly one worker process (`uvicorn documind.interfaces.api:app --workers 1`).
- **Rationale:** DocuMind uses embedded ChromaDB (`PersistentClient`), which persists embeddings to an embedded SQLite database and local HNSW index files on disk. Running multiple worker processes results in SQLite concurrent write locks (`database is locked`) and index state corruption.
- **Concurrency Boundary:** To safely handle concurrency, the application executes synchronous endpoints within FastAPI's threadpool and serializes mutating writes through a single internal `threading.Lock`. Read queries (`/v1/ask`) proceed concurrently without blocking on this write lock.

---

## 3. Local-Use-Only Design (No Built-in TLS or Remote Hardening)
- **Limitation:** The server binds to `127.0.0.1` by default and contains no native TLS/HTTPS termination engine.
- **Operational Requirement:** If binding to a non-loopback network interface (`--host 0.0.0.0`), TLS termination and perimeter access control must be handled by a production reverse proxy (e.g., Caddy, Nginx, or AWS ALB).
- **Warning:** `documind serve` emits an explicit warning when started on any non-loopback address.

---

## 4. No Cross-Origin Resource Sharing (CORS)
- **Limitation:** `CORSMiddleware` is deliberately omitted.
- **Rationale:** DocuMind is designed as a local-first backend for CLI, desktop MCP clients, and authenticated server-to-server HTTP consumers. Allowing arbitrary browser origins would introduce Cross-Site Request Forgery (CSRF) and local port scanning risks.

---

## 5. Adversarial Lexical Overlap & Hard Negatives (Under-Abstention)
- **Description:** Bi-encoder embedding models (such as `bge-small-en-v1.5`) map queries to dense vectors via average pooling over token representations. When an adversarial or unanswerable query (e.g., SQuAD 2.0 impossible questions) shares heavy lexical and topical overlap with an indexed document, the similarity score exceeds the abstention threshold ($\tau = 0.35$, scoring $0.65 - 0.70$).
- **Impact:** Stage 2 retrieval thresholding does not filter these adversarial hard negatives. Filtering depends entirely on the downstream LLM adhering to Stage 5 (`DECLINE_SENTINEL`).
- **Mitigation:** Grounded system prompt enforcing citations strictly from prompt context, XML source isolation, and citation syntax validation.

---

## 6. Intra-Document Semantic Competition
- **Description:** For lengthy, cohesive technical documents, multiple paragraphs discuss identical terminology with subtle semantic differences.
- **Impact:** Broad user questions frequently retrieve general introductory or summary sections at Rank 1, pushing the exact definition or quantitative answer into Ranks 2–4. This creates a gap between Recall@1 (~0.57) and Recall@5 (~0.84).
- **Mitigation:** Retrieval top-k parameter defaults to `top_k = 5` and prompt context includes all top-k retrieved chunks, allowing the generation model to synthesize evidence across complementary passages.
