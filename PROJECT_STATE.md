# DocuMind — Project State

## 1. Current Phase
**Phase 7: End-to-End Real Browser Verification & System Hardening** (Delivered & 100% Verified).

## 2. Key Architecture & Decisions (One Line Each)
- **Model Choice:** Multi-provider support (`anthropic`, `openai_compat`, `ollama`, `none`) auto-detecting Anthropic, Gemini (`GEMINI_API_KEY`), or OpenAI keys securely via `.env`.
- **Reusable Chat Drawer:** Implemented `Documind-frontend/chat-drawer.js` and `chat-drawer.css` as a sliding right-side drawer panel across all views (`console`, `library`, `proof`, `architecture`) without page navigation.
- **Chunk Count Bug Resolution:** Fixed frontend property access and backend payload to consistently return both `"chunks"` and `"chunk_count"` in upload and listing responses (`doc.chunks ?? doc.chunk_count ?? 0`), eliminating the "0 chunks" bug.
- **Transparent LLM State:** Distinguishes unconfigured language models (`outcome: "unconfigured_model"`) from relevance gate abstentions ($\tau < 0.35$), providing setup guidance banners without fabricating answers or exposing secrets.
- **Embedding & Storage:** 384-dim `BAAI/bge-small-en-v1.5` embeddings with cosine similarity in Chroma or in-memory Numpy.
- **Relevance Gate:** Threshold $\tau = 0.35$ enforced at retrieval; questions scoring below $\tau$ trigger early abstention before LLM synthesis.
- **Chunking Topology:** 200 words per window with 30-word overlap, preventing definition straddling.
- **Session Architecture:** Public demo routes scoped by server-issued opaque session tokens (`POST /api/demo/session`) with SHA-256 hash isolation in SQLite.
- **Storage Isolation:** Each demo tenant workspace physically isolated in `sessions/{session_hash}/` with independent vector store and document storage.
- **User Authentication:** Tenant isolation via `hashlib.scrypt` password hashing, SQLite user registry, CSRF double-submit cookies, and seamless guest-to-account workspace claiming (`claim_guest_workspace`).
- **Spend Protection:** Dual-layer spend control: global daily budget ($2.00/day) and per-session/IP allocations ($0.25/day) failing closed to `retrieval_only`.
- **Frontend Serving:** Single-origin static mounting via FastAPI at `/app` (`documind serve`) avoiding CORS latency and cross-origin leaks.
- **Layout & SVG Repairs:** Fixed pipeline diagram collisions in `console/code.html` (expanded viewBox to 780x150, separated abstain branch coordinates), corrected broken ticker metrics on `architecture/code.html`, and eliminated syntax errors.
- **Purposeful Motion:** Added tasteful, restrained CSS animations to 404 node-graph illustration (satellite pulses, dashed stroke flows) with strict `@media (prefers-reduced-motion: reduce)` accessibility compliance.
- **Console Workbench:** Real SSE execution stream with latency reporting, candidate chunk cosine similarity bars, live ring-buffer event logs with category filtering, and JSON export.

## 3. Measured Results & Benchmark Facts
- **Real Browser CDP Verification (`scratch/test_phase7_e2e_full.js`):** 11/11 phases passing in real Chrome CDP (Port 9222) with **ZERO console errors**.
  - 1. Console navigation & clean slate bootstrap.
  - 2. Guest session bootstrap (`DocuMindAPI.newSession()`).
  - 3. Dropzone document upload and dense chunk indexing.
  - 4. 384-dimensional dense vector embeddings inspection.
  - 5. Real-time SSE streaming chat tokens with interactive `[S1]` citation pill references.
  - 6. Automated confidence gate abstention on off-topic questions ($\tau = 0.35$).
  - 7. User registration with scrypt password hashing and guest workspace claiming.
  - 8. Authenticated tenant state verification (`/api/auth/me`).
  - 9. Session cookie authentication, logout, and re-login cycle.
  - 10. Authenticated workspace document deletion.
  - 11. Zero console errors throughout the entire lifecycle.
- **Static Page CDP Audit (`scratch/test_phase6_pages.js`):** Verified all 5 portal pages (`console`, `architecture`, `library`, `proof`, `chat.html`) in headless Chrome CDP with **0 red console errors**.
- **Full Backend Test Suite:** 274 passed, 13 skipped in 20.89s (zero failures).
- **Static Analysis:** `ruff check .` passed with 0 errors; `mypy documind` passed across 36 source files with 0 issues.
- **Security Hardening:** 100% tenant workspace isolation, CSRF double-submit protection, and scrypt credential hashing.

## 4. Next Action
All gated phases (Phase 0 through Phase 7) fully implemented, verified in Chrome CDP, and committed on branch `fix/ui-wiring`. Ready for deployment.



