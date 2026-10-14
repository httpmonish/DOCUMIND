# Changelog

All notable changes to DocuMind are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-10-14

### Added
- **Secure Read-Only MCP Server**: Native Model Context Protocol (MCP) server implementation in `documind.interfaces.mcp_server` using the official `mcp` 1.x SDK (`mcp>=1.29.0,<2`).
- **Stdio Transport**: Single-process standard I/O communication for desktop clients including Anthropic Claude Desktop and Claude Code CLI.
- **MCP Tools**:
  - `search_documents`: Semantic search with $\tau = 0.35$ relevance confidence gating and citation markers (`[S1]`, `[S2]`).
  - `get_chunk`: Chunk lookup by ID with configurable adjacent neighbor chunk expansion.
  - `list_documents`: Document enumeration with chunk counts and content SHA-256 hashes.
  - `index_info`: Index configuration, capacity metrics, and embedding parameters.
- **MCP Resources & Prompts**:
  - `documind://index/info` and `documind://chunk/{chunk_id}` resources.
  - `answer_from_documents` prompt instructing desktop models to cite grounded local evidence and abstain on low relevance.
- **CLI Commands**:
  - `documind mcp serve [--home PATH] [--log-level LEVEL]`: Runs the MCP stdio server.
  - `documind mcp config [--home PATH]`: Emits copy-paste configuration for Claude Desktop and Claude Code.
- **Doctor Diagnostic Checks**: Added `check_mcp` for verifying MCP SDK installation, index non-empty state, and Hugging Face embedding model cache.
- **Security Defenses**:
  - Untrusted document text and filename sanitization (stripping control chars and bidi overrides).
  - Delimiter and prompt token neutralization (`[S<n>]`, `<|im_end|>`).
  - Strict storage path resolution with automatic rejection of `sessions/*` paths.
  - Response character capping with explicit `truncated: true` flag.
  - Prohibition of networking, shell, and subprocess imports within `mcp_server.py`.
- **Architecture Decision Record**: Recorded in `docs/decisions/0010-mcp-server.md`.
- **Demo Script**: Interactive headless client demo in `examples/mcp_demo.py`.

## [0.6.0] - 2026-10-14

### Added
- Glass Box UI with interactive 3D document pipeline visualization.
- Multi-turn conversation persistence in SQLite with Server-Sent Events (SSE) streaming.
- Spend ledger ($2.00/day global, $0.25/day per-IP caps) and rate-limiting guards.
- Subprocess PDF sandboxing with `RLIMIT_AS` memory limits and timeouts.

## [0.4.0] - 2026-10-09

### Added
- Calibrated relevance gate ($\tau = 0.35$) with deterministic abstention (Exit Code 3).
- ChromaStore embedded vector persistence and in-memory NumpyStore.
- BAAI/bge-small-en-v1.5 dense bi-encoder retrieval.
- Verifiable citation validation against retrieved chunk boundaries.
