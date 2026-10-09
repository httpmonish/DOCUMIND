# DocuMind

> **Local-first semantic search and question-answering over your documents, returning grounded answers with verifiable citations.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Phase 4](https://img.shields.io/badge/Status-v0.4.0%20(CLI)-green.svg)](#status)

---

## Status
- **Current (Phase 4):** Production-grade CLI (`documind`) with offline diagnostic tooling (`doctor`), log aggregation (`stats`), and clean stream separation.
- **Planned:** REST API / FastAPI service (Phase 5) and Model Context Protocol (MCP) server for Claude Desktop (Phase 6).

---

## Installation

```bash
# 1. Clone and enter the repository
git clone https://github.com/httpmonish/DOCUMIND.git && cd DOCUMIND

# 2. Create virtual environment and install DocuMind with local embedding support
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[embed]"

# 3. Configure Anthropic API key (optional; run --no-llm for local retrieval only)
cp .env.example .env
echo "ANTHROPIC_API_KEY=your_key_here" >> .env
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

## Architecture: How It Works

```
[ Documents (PDF, MD, TXT) ] ──> [ Chunker (200w/30w) ] ──> [ BGE-Small Embedder ] ──> [ Chroma / Numpy Store ]
                                                                                               │
[ User Query ] ──────────────────> [ Bi-Encoder Query Vector ] ───(Cosine Similarity)─────────┘
                                                                │
                                    ┌───────────────────────────┴────────────────────────────┐
                                    ▼                                                        ▼
                        Score >= 0.35 (Grounded)                                   Score < 0.35 (Abstain)
                                    │                                                        │
                      [ Context Prompt Builder ]                                  [ Exit Code 3 Abstention ]
                                    │
                       [ Claude Haiku Generation ] ──> [ Cited Answer to stdout ]
                                                   ──> [ Execution Stats to stderr ]
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

---

## Exit Codes

| Code | Status | Meaning |
|:---:|---|---|
| `0` | Success | Answer generated, passages returned, document indexed or deleted |
| `1` | Internal Error | Unexpected internal exception (re-run with `--debug` for traceback) |
| `2` | Usage Error | Invalid arguments, `top_k` out of bounds, or non-interactive `rm` without `--yes` |
| `3` | Abstention | Unanswerable query, insufficient retrieval score, or empty index |
| `4` | Input Error | Unreadable document, missing path, or deleting unknown document |
| `5` | Configuration | Missing extra dependency or invalid API key |
| `6` | Index Error | Corrupt index metadata or mismatched embedding schema |

---

## REST API (Phase 5)

DocuMind provides a high-performance, secure REST interface powered by FastAPI and Uvicorn.

Start the server:
```console
$ documind serve --host 127.0.0.1 --port 8000
```

All endpoints under `/v1` require the `X-API-Key` header with a pre-configured key ($\ge$ 32 characters).

### 1. Upload & Index a Document (`POST /v1/documents`)
```console
$ curl -s -X POST "http://127.0.0.1:8000/v1/documents?replace=true" \
    -H "X-API-Key: test_key_minimum_32_characters_long_for_security_checks" \
    -F "file=@tests/fixtures/os_notes.md"
```
Output:
```json
{"status":"indexed","source":"os_notes.md","chunks":9,"sha256":"949a699b56a40c113b45340115b4c68eef4d9309ba1f7e1314683cedea1ec1ae"}
```

### 2. Ask a Grounded Question (`POST /v1/ask`)
```console
$ curl -s -X POST "http://127.0.0.1:8000/v1/ask" \
    -H "X-API-Key: test_key_minimum_32_characters_long_for_security_checks" \
    -H "Content-Type: application/json" \
    -d '{"question":"what is a semaphore","top_k":2}'
```
Output:
```json
{"text":"No language model is configured; returning relevant passages.","outcome":"abstained","abstain_reason":"no_llm","citations":[{"marker":"S1","source":"os_notes.md","chunk_index":3,"snippet":"Kernel-level threads are managed directly by the operating system kernel scheduler; while kernel context switches incur higher latency due to trap-handling overhead, blocking system calls on one threa","score":0.7833},{"marker":"S2","source":"os_notes.md","chunk_index":4,"snippet":"resume execution. Crucially, the testing, decrementing, and conditional suspension within `wait` and `signal` must execute indivisibly without interruption, typically enforced via hardware atomic inst","score":0.6894}],"model":"claude-haiku-4-5-20251001","usage":{"input_tokens":0,"output_tokens":0},"latency_ms":10}
```

### 3. Delete an Indexed Document (`DELETE /v1/documents/{source}`)
```console
$ curl -s -w "\nHTTP Status: %{http_code}\n" -X DELETE "http://127.0.0.1:8000/v1/documents/os_notes.md" \
    -H "X-API-Key: test_key_minimum_32_characters_long_for_security_checks"
```
Output:
```text
HTTP Status: 204
```

---

## Privacy & Streams

- **Strict Stream Separation:** Primary machine-readable data (answer text, search lists, or JSON) is emitted exclusively to `stdout`. All logs, stats footers, warnings, and error messages go to `stderr`. Piping `documind ask ... --json | jq .` will never fail due to runtime logs.
- **Privacy Model:** When running `ask` with an LLM, only the user question and the top-$k$ matching chunks are transmitted to the Anthropic API. Running `documind ask --no-llm` or `documind search` runs 100% locally on your machine with zero external network transmission.
