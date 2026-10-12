# DocuMind — Implementation Audit & Reconnaissance Report

**Audit Date:** 2026-10-10  
**Repository:** [https://github.com/httpmonish/DOCUMIND](https://github.com/httpmonish/DOCUMIND)  
**Scope:** Full-Stack Integration, Document Intelligence Agent, Session Isolation, and Public Live Demo  

---

## 1. Executive Summary

This audit assesses the state of DocuMind prior to Phase 1 full-stack integration. DocuMind possesses a robust, highly tested core Python library (`documind/core/`) and a hardened Phase 5 REST API (`documind/interfaces/api.py`). However, the existing frontend integration suffered from critical architectural vulnerabilities: browser-side secret exposure, hardcoded connection strings, lack of public demo authorization, absence of session isolation, and non-interactive UI prototypes.

---

## 2. Source Code & Interface Inspection

### 2.1 Backend Core (`documind/core/`)
- **Document Loading & Extraction:** `documind.core.loader.load_document` supports `.pdf`, `.txt`, and `.md`. PDF extraction executes in an isolated subprocess (`_extract_worker.py`) with a 60s timeout, 500-page limit, and POSIX memory caps (`RLIMIT_AS`).
- **Chunking:** `documind.core.chunker.chunk_document` splits text with sliding-window word preservation (default 200 words, 30 word overlap).
- **Embeddings:** `documind.core.embedder.SentenceTransformerEmbedder` loads `BAAI/bge-small-en-v1.5` generating 384-dimensional L2-normalized float32 vectors.
- **Vector Storage:** 
  - `NumpyStore`: In-memory exact dot-product store.
  - `ChromaStore`: Embedded ChromaDB (`PersistentClient`) with cosine similarity.
- **Retrieval & Relevance Gate:** `Retriever` executes semantic search and evaluates top-1 chunk score against relevance threshold ($\tau = 0.35$). If below $\tau$, the pipeline triggers clean abstention (Exit Code 3).
- **Prompt & Answer Generation:** `build_prompt` isolates sources within XML tags. `AnthropicLLM` invokes `claude-haiku-4-5-20251001` or operates in local retrieval-only mode if `ANTHROPIC_API_KEY` is omitted.
- **Citation Parsing & Verification:** `parse_citations` parses markers (`[S1]`, `[S2]`) and validates that every marker matches a retrieved chunk.

### 2.2 Backend API (`documind/interfaces/api.py`)
- Built on FastAPI with Uvicorn.
- **Fail-Closed Lifespan:** Fails startup if `DOCUMIND_API_KEY` is missing or $< 32$ characters.
- **Protected `/v1` Router:** Requires `X-API-Key` validated via timing-safe `hmac.compare_digest`.
- **Existing Endpoints:**
  - `GET /healthz` (Unauthenticated): returns engine chunk count, embed model, tau, schema version.
  - `POST /v1/documents` (Protected): multipart streaming file upload with 50MB cap and MIME/extension verification.
  - `GET /v1/documents` (Protected): lists distinct indexed document sources and chunk counts.
  - `POST /v1/ask` (Protected): queries document engine with question length and top_k bounds.
  - `GET /v1/documents/{source:path}/chunks` (Protected): lists chunks for a specific document.
  - `DELETE /v1/documents/{source:path}` (Protected): unindexes document.
  - `GET /v1/events` (Protected): returns in-memory query ring-buffer.
  - `GET /v1/eval` (Protected): returns evaluation benchmark report if present.
  - `GET /v1/meta` (Protected): returns system metadata.

### 2.3 Frontend Prototypes (`Documind-frontend/`)
The frontend contains 4 view exports based on the "Glass Box" UI design:
1. `stitch_documind_glass_box_ui/code.html`: Overview & Architecture view.
2. `stitch_documind_glass_box_ui (1)/code.html`: Interactive Console view (question input, telemetry ribbon, synthesized answer card, candidate chunks inspector, event log).
3. `stitch_documind_glass_box_ui (2)/code.html`: Proof & Verification view (benchmarks, threat matrix, cryptographic audit).
4. `stitch_documind_glass_box_ui (3)/code.html`: Library view (file upload drop zone, 5-step pipeline strip, document index list, chunk visualizer).

---

## 3. Verified Root Causes of Connection Failures

| Defect ID | Defect Description | Root Cause | Security / Operational Impact |
|---|---|---|---|
| **BUG-01** | **Browser-Side API Key Exposure** | `Documind-frontend/api.js` embedded `const API_KEY = "documind-secret-key-..."` directly in client source. | Severe: Any visitor can extract administrative credentials, bypass rate limits, and tamper with documents. |
| **BUG-02** | **Hardcoded Connection String** | `Documind-frontend/api.js` hardcoded `const API = "http://127.0.0.1:8000"`. | Fragile: Fails when deployed to remote hosts, staging domains, or reverse proxies without source code edits. |
| **BUG-03** | **Unauthenticated Public Access Failure** | The `/v1/*` routes strictly require `X-API-Key`. Anonymous public demo users have no key and receive HTTP 401 Unauthorized on all operational endpoints. | Blocker: The public live demo cannot function without exposing the master key. |
| **BUG-04** | **Absence of Multi-User Document Isolation** | The backend index (`~/.documind/chroma`) is a shared global singleton. | Severe Privacy Hazard: Uploaded documents from one visitor are visible, searchable, and deletable by any other visitor. |
| **BUG-05** | **Inert UI Elements & Static Mocks** | Query button, drop zone, deletion buttons, and analysis actions in HTML prototypes lacked event listeners and dynamic DOM rendering. | User Experience: Prototype appears non-functional despite working backend capabilities. |
| **BUG-06** | **Lack of Staged Progress & Error States** | Missing client-side request timeout handling, duplicate submit guards, and structured error extraction. | Fragile: Network errors or long embedding jobs trigger silent failure or unresponsive buttons. |

---

## 4. Route-to-UI Mapping

| UI Screen / Element | Trigger / Event | Gateway Endpoint | Backend Method | Expected Response / UI Effect |
|---|---|---|---|---|
| **Architecture Header & Cards** | Page Load (`DOMContentLoaded`) | `/healthz` | `GET` | Updates total chunks, embed model, and tau metric. |
| **Library: Document Drop Zone** | File drop or file picker change | `/api/demo/documents` | `POST (multipart)` | Displays 5-step progress (Validate -> Extract -> Chunk -> Embed -> Store), updates document list. |
| **Library: Document Index List** | Page Load / Post-Upload | `/api/demo/documents` | `GET` | Renders session-scoped documents, chunk counts, and SHA-256 hashes. |
| **Library: Chunk Visualizer** | Click document row | `/api/demo/documents/{source}/chunks` | `GET` | Displays individual chunk text, index, and Chroma metadata. |
| **Library: Delete Document** | Click "Delete this document" | `/api/demo/documents/{source}` | `DELETE` | Removes document from session index; refreshes document list. |
| **Console: Run Query Button** | Click / Enter in `#query-input` | `/api/demo/ask` | `POST` | Renders synthesized answer, citation pills, candidate chunk score bars, and latency. |
| **Console: Analysis Actions** | Click "Summarize", "Key points" | `/api/demo/analyze` | `POST` | Triggers structured document intelligence prompts on session context. |
| **Console: Candidate Inspector** | Post-query completion | `/api/demo/ask` response | `POST` | Maps top-$k$ retrieved chunks with relative score vs $\tau = 0.35$. |
| **Console: Telemetry Ribbon** | Post-query completion | `/api/demo/events` | `GET` | Populates live execution trace with end-to-end millisecond timing. |

---

## 5. Architectural Remediation Plan

1. **Server-Side Session Gateway (`/api/demo/*`):**
   - Provide an unauthenticated public gateway specifically designed for anonymous visitors.
   - Require/issue an opaque `X-Session-ID` validated with `^[a-zA-Z0-9_-]{16,64}$`.
   - Implement `SessionManager` providing isolated `DocuMind` engine instances per session workspace in `DOCUMIND_HOME/sessions/{session_id}`.
2. **Strict Multi-User Isolation:**
   - Every session has an independent document directory and vector store.
   - Cross-session retrieval, listing, chunk inspection, and deletion are physically prevented.
   - Expired sessions cleaned up via automatic TTL sweep.
3. **Hardened Client API (`Documind-frontend/api.js`):**
   - Zero credentials in client JavaScript.
   - Configurable base URL via `window.DOCUMIND_API_URL` or relative origin.
   - Automatic session management (`sessionStorage`).
   - AbortController timeout handling (30s).
   - Structured error envelope parsing (`code`, `message`, `request_id`).
   - Duplicate submission protection.
4. **Dynamic UI Wiring:**
   - Wire all query inputs, file uploads, analysis shortcuts, and citations across Console and Library views.
