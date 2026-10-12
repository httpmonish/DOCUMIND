# DocuMind — Project State

## 1. Current Phase
**Phase A Completed; Moving to Phase B: Public Demo Hardening & Abuse Defenses** (Gated).

## 2. Key Architecture & Decisions (One Line Each)
- **Model Choice:** Configurable via `DOCUMIND_MODEL` (default `claude-haiku-4-5-20251001`), never hardcoded in source.
- **Embedding & Storage:** 384-dimensional `BAAI/bge-small-en-v1.5` dense embeddings with cosine similarity in Chroma or in-memory Numpy.
- **Relevance Gate:** Threshold $\tau = 0.35$ enforced at retrieval; questions scoring below $\tau$ trigger early abstention before LLM synthesis.
- **Chunking Topology:** 200 words per window with 30-word overlap, preventing definition straddling (`no_gold = 0`).
- **Session Architecture:** Public demo routes scoped by server-issued opaque session tokens (`POST /api/demo/session`) with SHA-256 hash isolation in SQLite.
- **Storage Isolation:** Each demo tenant workspace isolated in `sessions/{session_hash}/` with independent vector store and document storage.
- **Spend Protection:** Dual-layer spend control: global daily budget ($2.00/day) and per-session/IP allocations failing closed to `retrieval_only`.
- **Frontend Serving:** Single-origin static mounting via FastAPI (`documind serve`) avoiding CORS latency and cross-origin leaks.
- **API Boundary Separation:** Admin routes (`/v1/*`) protected by 32+ char `X-API-Key`; public demo routes (`/api/demo/*`) protected by session hashes and rate limits.

## 3. Measured Results & Benchmark Facts
- **Full Test Suite:** 238 passed, 16 deselected (`slow` or `live`) in 5.81s.
- **Static Analysis:** `ruff check .` passed with 0 errors; `mypy documind` passed across 31 source files.
- **Frontend Smoke Tests:** `tests/test_frontend_smoke.py` passes all 3 end-to-end tests (mounts, valid api.js, document ingest, chunk alignment, tau = 0.35, query answering).
- **Placeholder Free:** Grep across `Documind-frontend/` confirms 0 instances of `1,240`, `12 documents`, `0.45`, `3,006`.
- **Commit:** `12f9a5f` (Phase 0 restored baseline).
- **Primary Eval Retrieval (n=200 SQuAD):** Recall@1 = 0.575, Recall@3 = 0.795, Recall@5 = 0.840, Recall@10 = 0.930, MRR@10 = 0.692.
- **E2E Test Split (n=33):** Recall@5 = 1.000, Faithfulness = 1.000, Correctness = 1.000, False-Abstain = 0.000, Off-Topic Abstain = 1.000, Citation Precision = 0.909.
- **Judge Calibration (n=20):** Observed Agreement = 1.0000, Cohen's Kappa = 1.0000 across 3-class correctness and full faithfulness.
- **Per-Query Token Economics:** Average ~1,700 input tokens, ~80–120 output tokens, measured generation cost = $0.00214 / query (Haiku 4.5).
- **Abstention Threshold Sweep ($\tau \in [0.20, 0.80]$):** At $\tau = 0.35$, False-Abstain Rate is 0.000 (0/200 on-topic) while rejecting 100% of off-topic queries.

## 4. Open Questions & Unknowns
1. **Hosting Target for Demo:** Platform environment (e.g. VPS, Render, Fly.io) determining proxy topology and port isolation.
2. **Monthly Provider Spend Limit:** Target monthly limit configured in Anthropic Console workspace.
3. **Serving Origin Preference:** Confirmation of same-origin FastAPI static serving (recommended) vs separate frontend host.
4. **Playwright Environment Support:** Environment Playwright browser driver download failed with 404 from external CDN; need confirmation on headless browser setup vs Node/Python smoke test suite.

## 5. Next Action
Execute Phase B (Security & Abuse Hardening): SQLite session registry with server-issued tokens, IP client resolution with trusted proxies and IPv6 /64, sliding window rate limits, daily spend ledger failing closed to `retrieval_only`, upload limits and prompt delimiter escaping.
