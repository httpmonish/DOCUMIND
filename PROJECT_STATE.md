# DocuMind — Project State

## 1. Current Phase
**Phase C Completed; Final Phase D: Verification, Tagging & Release Delivery** (Gated).

## 2. Key Architecture & Decisions (One Line Each)
- **Model Choice:** Configurable via `DOCUMIND_MODEL` (default `claude-haiku-4-5-20251001`), never hardcoded in source.
- **Embedding & Storage:** 384-dimensional `BAAI/bge-small-en-v1.5` dense embeddings with cosine similarity in Chroma or in-memory Numpy.
- **Relevance Gate:** Threshold $\tau = 0.35$ enforced at retrieval; questions scoring below $\tau$ trigger early abstention before LLM synthesis.
- **Chunking Topology:** 200 words per window with 30-word overlap, preventing definition straddling (`no_gold = 0`).
- **Session Architecture:** Public demo routes scoped by server-issued opaque session tokens (`POST /api/demo/session`) with SHA-256 hash isolation in SQLite.
- **Storage Isolation:** Each demo tenant workspace isolated in `sessions/{session_hash}/` with independent vector store and document storage.
- **Spend Protection:** Dual-layer spend control: global daily budget ($2.00/day) and per-session/IP allocations failing closed to `retrieval_only`.
- **Frontend Serving:** Single-origin static mounting via FastAPI at `/app` (`documind serve`) avoiding CORS latency and cross-origin leaks.
- **API Boundary Separation:** Admin routes (`/v1/*`) protected by 32+ char `X-API-Key`; public demo routes (`/api/demo/*`) protected by session hashes and rate limits.
- **Multi-Turn Chat Architecture:** SQLite `conversations` & `messages` tables, query condensation (`condense_query`), neighbor expansion (`expand_neighbors`), and AsyncAnthropic SSE streaming (`POST /api/demo/chat/stream`).

## 3. Measured Results & Benchmark Facts
- **Full Test Suite:** 254 passed, 16 deselected (`slow` or `live`) in 6.24s.
- **Static Analysis:** `ruff check .` passed with 0 errors; `mypy documind` passed across 35 source files with 0 issues.
- **Multi-Turn & Streaming (Phase C):** 4/4 dedicated integration tests pass (`tests/test_multiturn.py`), validating SQLite threads, query rewriting, chunk expansion, and SSE events (`meta`, `retrieval`, `token`, `citations`, `done`).
- **Security Hardening (Phase B):** 12/12 dedicated security tests pass (`tests/test_demo_security.py`).
- **Server Sessions:** Client-chosen session tokens rejected with 401 `SESSION_INVALID`; expired tokens rejected with 401 `SESSION_EXPIRED`.
- **Rate Limiting:** Multi-action token bucket enforces 10 asks/min, 5 uploads/hr, 5 sessions/hr with IPv6 `/64` normalization.
- **Spend Control:** Two-phase commit ledger enforces $2.00 global and $0.25 IP daily caps, failing closed to `retrieval_only` (0 HTTP 500s).
- **Upload Hardening:** 10MB streaming abort, 415 on non-text/pdf extensions, 5 document / 20MB per-session ceiling enforced.
- **Frontend Smoke Tests:** `tests/test_frontend_smoke.py` passes all 3 end-to-end tests (mounts, valid api.js, document ingest, chunk alignment, tau = 0.35, query answering).
- **Placeholder Free:** Grep across `Documind-frontend/` confirms 0 instances of `1,240`, `12 documents`, `0.45`, `3,006`.
- **Primary Eval Retrieval (n=200 SQuAD):** Recall@1 = 0.575, Recall@3 = 0.795, Recall@5 = 0.840, Recall@10 = 0.930, MRR@10 = 0.692.
- **E2E Test Split (n=33):** Recall@5 = 1.000, Faithfulness = 1.000, Correctness = 1.000, False-Abstain = 0.000, Off-Topic Abstain = 1.000, Citation Precision = 0.909.
- **Per-Query Token Economics:** Average ~1,700 input tokens, ~80–120 output tokens, measured generation cost = $0.00214 / query (Haiku 4.5).

## 4. Open Questions & Unknowns
1. **Hosting Target for Demo:** Platform environment (e.g. VPS, Render, Fly.io) determining proxy topology and port isolation.
2. **Monthly Provider Spend Limit:** Target monthly limit configured in Anthropic Console workspace.

## 5. Next Action
Execute Phase D: Final documentation alignment (`API_CONTRACT.md`, `README.md`), full test suite gate verification, and release tagging (`phase-6`).
