# DocuMind — Project State

## 1. Current Phase
**Phase 0: Orientation, Backup, and Read-Only Integrity Audit** (Gated).

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
- **Full Test Suite (Pre-corruption):** 235 passed, 16 deselected (`slow` or `live`) in 5.42s.
- **Current Test Suite (Corrupted State):** 172 passed, 1 failed (`test_serve_command_loopback_and_non_loopback_warning`), 8 collection errors due to empty `documind/interfaces/api.py`.
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
Await user confirmation on the Phase 0 audit report and approval of the recovered diffs to restore the 6 damaged files, run the full test suite (`ruff`, `mypy`, `pytest`), and enter Phase A.
