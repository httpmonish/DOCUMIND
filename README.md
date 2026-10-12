# DocuMind

> **Local-first semantic search and grounded question-answering over your documents, returning answers with verifiable citations and deterministic relevance gating.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Phase 6](https://img.shields.io/badge/Status-v0.6.0%20(Full--Stack%20RAG)-green.svg)](#status)
[![Tests: 257 Passed](https://img.shields.io/badge/tests-257%20passed-brightgreen.svg)](#testing--verification)
[![Type Checked: Mypy](https://img.shields.io/badge/type--check-mypy%20strict-blue.svg)](#testing--verification)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-black.svg)](#testing--verification)

---

## Highlights

- **Local-First & Private:** Local document extraction, sliding-window chunking, dense vector embeddings (`BAAI/bge-small-en-v1.5`), and similarity search without cloud dependencies.
- **Relevance Gate & Abstention ($\tau = 0.35$):** Pre-generation similarity gating prevents hallucination; queries lacking support in the indexed documents cleanly abstain (Exit Code 3).
- **Verifiable Citations:** Responses cite precise chunk anchors (`[S1]`, `[S2]`) with matching source filenames and snippet similarity scores.
- **Dual API Boundary:**
  - **Admin Microservices (`/v1/*`):** Protected by 32+ character API keys evaluated via timing-safe `hmac.compare_digest`.
  - **Public Demo Gateway (`/api/demo/*`):** Anonymous visitor access with server-issued opaque session tokens and complete tenant workspace isolation.
- **Multi-Turn Chat & SSE Streaming:** Query condensation (`condense_query`), neighbor chunk expansion, conversation history in SQLite, and real-time Server-Sent Events (`POST /api/demo/chat/stream`).
- **Spend & Resource Protection:** Token-bucket rate limiting (IPv6 `/64` normalization) and two-phase spend ledger ($2.00/day global, $0.25/day per-IP caps) failing closed to retrieval-only mode.
- **Subprocess Sandboxing:** PDF text extraction executes in isolated POSIX subprocesses with 60-second timeouts, 500-page limits, and address-space memory caps (`RLIMIT_AS`).
- **Glass Box UI:** Built-in web console mounted at `/app` providing deep operational visibility: Console, Ingestion Library, Proof & Verification, and Architecture.

---

## Status

- **Current (Phase 6 / v0.6.0):** Full-stack grounded document intelligence engine with Glass Box UI, server-issued session isolation in SQLite, spend ledger & rate-limiting guards, multi-turn chat persistence, neighbor chunk expansion, and AsyncAnthropic SSE streaming (`text/event-stream`).
- **Administrative Core:** REST API (`/v1/*`) secured by 32+ character API keys for trusted programmatic microservices.

---

## Architecture: How It Works

```
[ Documents (PDF, MD, TXT) ] ──> [ Subprocess Ingestion & Sandboxing ]
                                           │
                                           ▼
                                 [ Chunker (200w/30w) ] ──> [ BGE-Small Embedder (384d) ]
                                                                        │
                                                                        ▼
                                                             [ Chroma / Numpy Store ]
                                                                        │
[ User Query ] ──────────────────> [ Bi-Encoder Vector ] ───────────────┤ (Cosine Similarity)
                                                                        │
                                    ┌───────────────────────────────────┴───────────────────────────────────┐
                                    ▼                                                                       ▼
                        Score >= 0.35 (Grounded)                                                  Score < 0.35 (Abstain)
                                    │                                                                       │
                      [ Context Prompt Builder ]                                                 [ Exit Code 3 Abstention ]
                                    │
                      [ Multi-Turn Condenser + Expansion ]
                                    │
                      [ Claude Haiku / SSE Streaming ] ──> [ Cited Answer to stdout / SSE stream ]
                                                       ──> [ Telemetry & Token Stats to stderr ]
```

---

## Installation

```bash
# 1. Clone and enter the repository
git clone https://github.com/httpmonish/DOCUMIND.git && cd DOCUMIND

# 2. Create virtual environment and install DocuMind with local embedding support
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[embed]"

# 3. Configure LLM Provider (Optional; defaults to 0-key retrieval-only mode)
cp .env.example .env
# Choose provider in .env:
# DOCUMIND_LLM_PROVIDER=none          # Zero-key retrieval-only mode (Default)
# DOCUMIND_LLM_PROVIDER=ollama        # Local free inference (e.g. Llama 3 via http://localhost:11434/v1)
# DOCUMIND_LLM_PROVIDER=openai_compat # Groq, Gemini, vLLM, or OpenAI-compatible endpoint
# DOCUMIND_LLM_PROVIDER=anthropic     # Claude Haiku (set ANTHROPIC_API_KEY)
```

---

## Quickstart

Verify environment and index local documentation:

```console
$ documind doctor
[ok] python: Python 3.12.14
[ok] anthropic key: ANTHROPIC_API_KEY is set (sk-ant-...c123)
[ok] home: Home directory exists at /Users/monish/.documind
[ok] index meta: Embedding model: BAAI/bge-small-en-v1.5
[ok] embedder: sentence-transformers is installed
[ok] vector store: chromadb is installed
[ok] llm client: anthropic is installed

$ documind index ./docs
indexed   operating_systems.md
indexed   memory_management.pdf
2 indexed, 0 skipped, 0 failed, 8 chunks in 0.4s

$ documind ask "what is a semaphore?"
A semaphore is a synchronization primitive that uses an integer counter to control access to shared system resources. [S1]

Sources:
[S1] operating_systems.md#0  (0.8142)  A semaphore is a synchronization variable that controls access to common resources.

$ documind ask "what is a semaphore?" --json
{
  "text": "A semaphore is a synchronization primitive...",
  "outcome": "answered",
  "abstain_reason": null,
  "citations": [
    {
      "marker": "S1",
      "source": "operating_systems.md",
      "chunk_index": 0,
      "snippet": "A semaphore is a synchronization variable...",
      "score": 0.8142
    }
  ],
  "model": "claude-haiku-4-5-20251001",
  "usage": { "input_tokens": 1700, "output_tokens": 300 },
  "latency_ms": 1120
}
```

---

## Commands

| Command | Description |
|---|---|
| `documind index PATH [--root DIR] [--json]` | Parse, chunk, and index PDFs, text, and markdown files |
| `documind ask QUESTION [--top-k N] [--json] [--no-llm] [--show-prompt]` | Query documents with grounded citation generation |
| `documind search QUESTION [--top-k N] [--json]` | Perform semantic similarity search returning ranked chunks |
| `documind ls [--json]` | List all indexed documents and chunk counts |
| `documind rm SOURCE [--yes]` | Delete an indexed document from storage |
| `documind doctor [--json]` | Run diagnostic environment and index consistency checks |
| `documind stats [--days N] [--json]` | Analyze query volume, abstention rates, and latency percentiles |
| `documind serve [--host IP] [--port N]` | Start unified REST API and Glass Box UI web server |

---

## Exit Codes

| Code | Status | Meaning |
|:---:|---|---|
| `0` | Success | Answer generated, passages returned, document indexed or deleted |
| `1` | Internal Error | Unexpected internal exception (re-run with `--debug` for traceback) |
| `2` | Usage Error | Invalid arguments, `top_k` out of bounds, or non-interactive `rm` without `--yes` |
| `3` | Abstention | Unanswerable query, insufficient retrieval score ($\tau < 0.35$), or empty index |
| `4` | Input Error | Unreadable document, missing path, or deleting unknown document |
| `5` | Configuration | Missing extra dependency or invalid API key |
| `6` | Index Error | Corrupt index metadata or mismatched embedding schema |

---

## Glass Box Web UI

DocuMind includes a built-in Glass Box interface mounted directly alongside the API at `/app`.

Start the application server:
```console
source .venv/bin/activate
documind serve --host 127.0.0.1 --port 8000
```

Open your browser to:
- **Interactive Console:** `http://127.0.0.1:8000/app/console/code.html`  
  *Direct question input, token usage ribbon, synthesized answers, candidate score bars, and execution trace.*
- **Ingestion & Library:** `http://127.0.0.1:8000/app/library/code.html`  
  *Drag-and-drop document upload, 5-stage ingestion progress, chunk inspection, and document deletion.*
- **Proof & Telemetry:** `http://127.0.0.1:8000/app/proof/code.html`  
  *Real-time benchmark verification, threat mitigation matrix, and cryptographic SHA-256 chunk audits.*
- **Architecture Overview:** `http://127.0.0.1:8000/app/architecture/code.html`  
  *Interactive topology, threshold calibration, and spend ledger telemetry.*

---

## Multi-Turn Chat & SSE Streaming

DocuMind supports conversational threads with query condensation and live Server-Sent Events (SSE):

### 1. Acquire Visitor Session Token
```console
$ curl -s -X POST "http://127.0.0.1:8000/api/demo/session"
```
```json
{
  "session_token": "a1b2c3d4e5f60718293a4b5c6d7e8f90...",
  "created_at": 1728564000,
  "expires_at": 1728650400
}
```

### 2. Stream Live Answer Tokens via SSE
```console
$ curl -N -X POST "http://127.0.0.1:8000/api/demo/chat/stream" \
    -H "X-Session-ID: <session_token>" \
    -H "Content-Type: application/json" \
    -d '{
      "message": "how does the operating system handle context switching?",
      "top_k": 3
    }'
```

Stream format:
```text
event: meta
data: {"conversation_id": "c-4f1b...", "session_id": "...", "model": "claude-haiku-4-5-20251001"}

event: retrieval
data: {"chunks_retrieved": 3, "top_score": 0.812, "abstained": false}

event: token
data: {"token": "Context "}

event: token
data: {"token": "switching "}

event: token
data: {"token": "saves "}

event: citations
data: [{"marker": "S1", "source": "os_notes.md", "chunk_index": 2, "score": 0.812}]

event: done
data: {"status": "completed", "latency_ms": 640}
```

---

## Administrative REST API (`/v1/*`)

All `/v1` endpoints require `X-API-Key: <DOCUMIND_API_KEY>` ($\ge 32$ chars, checked via constant-time HMAC):

### 1. Upload & Index a Document (`POST /v1/documents`)
```console
$ curl -s -X POST "http://127.0.0.1:8000/v1/documents?replace=true" \
    -H "X-API-Key: $DOCUMIND_API_KEY" \
    -F "file=@tests/fixtures/os_notes.md"
```
```json
{
  "status": "indexed",
  "source": "os_notes.md",
  "chunks": 9,
  "sha256": "949a699b56a40c113b45340115b4c68eef4d9309ba1f7e1314683cedea1ec1ae"
}
```

### 2. Ask a Grounded Question (`POST /v1/ask`)
```console
$ curl -s -X POST "http://127.0.0.1:8000/v1/ask" \
    -H "X-API-Key: $DOCUMIND_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"question":"what is a semaphore","top_k":2}'
```

### 3. Delete an Indexed Document (`DELETE /v1/documents/{source}`)
```console
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X DELETE "http://127.0.0.1:8000/v1/documents/os_notes.md" \
    -H "X-API-Key: $DOCUMIND_API_KEY"
# HTTP Status: 204
```

---

## Public Demo Endpoints (`/api/demo/*`)

| Endpoint | Method | Description |
|---|:---:|---|
| `/api/demo/session` | `POST` | Acquire server-issued opaque session token |
| `/api/demo/documents` | `GET` | List documents in current visitor session |
| `/api/demo/documents` | `POST` | Upload & chunk PDF, TXT, or MD into session workspace |
| `/api/demo/documents/{source}` | `DELETE` | Delete a document from session workspace |
| `/api/demo/documents/{source}/chunks` | `GET` | Inspect chunk partition text and index order |
| `/api/demo/ask` | `POST` | Grounded Q&A with single-turn context |
| `/api/demo/chat` | `POST` | Multi-turn chat with follow-up query condensation |
| `/api/demo/chat/stream` | `POST` | Live token-by-token SSE stream (`text/event-stream`) |
| `/api/demo/conversations` | `GET` | List visitor conversation threads |
| `/api/demo/conversations/{id}/messages` | `GET` | List thread messages with citations |
| `/api/demo/analyze` | `POST` | Bounded tasks (`summarize`, `key_points`, `explain`) |
| `/api/demo/events` | `GET` | Live telemetry event stream |
| `/api/demo/meta` | `GET` | Active model, tau threshold, and limits |

---

## Empirical Benchmarks & Evaluation

Evaluation performed on SQuAD 2.0 evaluation sets with deterministic hashing splits:

### Retrieval Baseline ($n = 200$ SQuAD Articles)
- **Model:** `BAAI/bge-small-en-v1.5` on `NumpyStore`
- **Topology:** 200 words / 30 words overlap (`no_gold = 0`)

| Metric | Measured Score | 95% Wilson CI | Target |
|---|:---:|:---:|:---:|
| **Recall@1** | 0.575 | [0.506, 0.641] | Baseline |
| **Recall@3** | 0.795 | [0.734, 0.845] | — |
| **Recall@5** | **0.840** | [0.783, 0.884] | $\ge 0.80$ |
| **Recall@10** | **0.930** | [0.886, 0.958] | — |
| **MRR@10** | **0.692** | — | $\ge 0.65$ |
| **Warm Retrieval Latency** | **4.8 ms (p50)** / **5.9 ms (p95)** | — | $\le 20\text{ ms}$ |

### End-to-End Generation Grounding ($n = 33$ Test Split)
- **Generator:** `claude-haiku-4-5-20251001`
- **Judge:** Calibrated `claude-sonnet-5-5` (100% agreement on calibration set)

| Metric | Measured Value | Gate Requirement | Status |
|---|:---:|:---:|:---:|
| **Recall@5** | **1.000** (22/22) | $\ge 0.85$ | **PASS** |
| **Faithfulness** | **1.000** (22/22) | $\ge 0.90$ | **PASS** |
| **Correctness** | **1.000** (22/22) | $\ge 0.80$ | **PASS** |
| **False-Abstain Rate** | **0.000** (0/22) | $\le 0.10$ | **PASS** |
| **Off-Topic Abstain Rate** | **1.000** (5/5) | $\ge 0.90$ | **PASS** |
| **Citation Precision** | **0.909** (20/22) | $\ge 0.85$ | **PASS** |
| **Generation Cost / Query** | **$0.00214** | $\le \$0.005$ | **PASS** |

---

## Security & Spend Protection

- **Tenant Isolation:** Public demo sessions are segregated in `~/.documind/sessions/{session_hash}/` with independent vector stores, document storage, and SQLite threads.
- **Two-Phase Spend Ledger:** Allocates query budget before invoking external APIs. Caps spend at $2.00/day globally and $0.25/day per IP; fails closed to retrieval-only mode with 0 unhandled exceptions.
- **Token-Bucket Rate Limiter:** Enforces 10 asks/min, 5 uploads/hr, and 5 sessions/hr with IPv6 `/64` subnet aggregation.
- **Subprocess Worker:** PDF parsing runs in isolated POSIX processes capped with `resource.setrlimit(resource.RLIMIT_AS)`.
- **Prompt Injection Canary Suite:** 20 canary test cases across multiple injection patterns verifying that untrusted document contents cannot hijack prompt instructions.

---

## Architecture Decision Records (ADRs)

All engineering decisions are documented under [`docs/decisions/`](docs/decisions/):

| ADR | Title | Decision Summary |
|---|---|---|
| [0001](docs/decisions/0001-embedding-model.md) | Embedding Model | `BAAI/bge-small-en-v1.5` for local execution, 384d density, and high MTEB score |
| [0002](docs/decisions/0002-vector-store.md) | Vector Store | In-memory `NumpyStore` for exact evals; embedded `ChromaDB` for persistence |
| [0003](docs/decisions/0003-chunking.md) | Chunking Topology | 200 words window with 30-word overlap preventing definition straddling |
| [0004](docs/decisions/0004-llm-provider.md) | LLM Provider | Claude Haiku 4.5 default with strict XML source isolation tags |
| [0005](docs/decisions/0005-interface-split.md) | Interface Boundaries | Administrative `/v1/*` (API key) split from Public Demo `/api/demo/*` (sessions) |
| [0006](docs/decisions/0006-concurrency.md) | Concurrency Model | Non-blocking async endpoints with thread-pool delegation for CPU embeddings |
| [0007](docs/decisions/0007-storage-layout.md) | Storage Layout | Quarantined storage under `~/.documind/` with dedicated `sessions/` trees |
| [0008](docs/decisions/0008-abstention-threshold.md) | Abstention Threshold | Calibrated relevance gate $\tau = 0.35$ balancing recall and false abstentions |
| [0009](docs/decisions/0009-cli-framework.md) | CLI Framework | Click-based subcommands with strict stdout data / stderr diagnostics separation |

---

## Testing & Verification

Run the full validation suite:

```bash
# Run 257 unit, integration, and security tests
.venv/bin/pytest

# Run static analysis & style checks
.venv/bin/ruff check .

# Run strict type checking across all modules
.venv/bin/mypy documind
```

---

## Privacy & Streams

- **Strict Stream Separation:** Machine-readable payloads (answer text, search lists, or JSON) are emitted exclusively to `stdout`. Logs, execution statistics, warnings, and error messages go to `stderr`. Piping `documind ask ... --json | jq .` is guaranteed clean.
- **Privacy Model:** When running `ask` with an LLM, only the user question and top-$k$ relevant chunks are sent to the Anthropic API. Running `documind ask --no-llm` or `documind search` runs 100% locally on your device with zero network egress.
