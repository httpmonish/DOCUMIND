# 0005. Core Engine and Interface Split

## Context
DocuMind supports multiple consumer interfaces: CLI, FastAPI REST service, and an MCP server for Claude Desktop. The retrieval, embedding, and LLM synthesis core must remain maintainable with zero duplication across interfaces, while preserving clean error reporting and boundary enforcement.

## Options
1. **REST-first Monolith (CLI and MCP call a running HTTP server)**:
   - Requires a daemon server continuously running.
   - IPC latency: adds 5–20 ms per request.
   - High debugging complexity when testing retrieval core in unit tests.
2. **Framework Monolith (LangChain / LlamaIndex)**:
   - Enormous dependency footprint (>50 transitive packages, >500 MB).
   - Tightly couples retrieval logic to proprietary framework abstractions.
3. **Pure Core Library with Thin Adapters (Chosen)**:
   - `documind/core/` is a pure Python library that imports zero interface frameworks (`fastapi`, `starlette`, `uvicorn`, `mcp`, `argparse`, `click`).
   - Zero IPC overhead for CLI and MCP.
   - AST-based architecture guard (`tests/test_architecture.py`) statically enforces zero leakage.
   - Core returns structured `Answer` objects with explicit `abstain_reason` (`empty_index`, `low_score`, `no_llm`, `llm_unavailable`).
   - REST adapter maps domain errors cleanly: empty index yields HTTP 409 (`code="index_empty"`), while LLM failure yields HTTP 502 with fallback citations.

## Decision
Keep `documind/core/` completely pure and decoupled. All interface adapters (`interfaces/cli.py`, `interfaces/api.py`, `interfaces/mcp.py`) import from core, but core never imports from interfaces. The REST adapter implements FR8 as a thin wrapper: authenticates, validates inputs, invokes a single `DocuMind` method, and serializes responses. For an empty index, `/v1/ask` returns HTTP 409 (`index_empty`) rather than an abstained 200, allowing API clients to distinguish an unpopulated index from a query with no relevant matches.

## You give up X to get Y
You give up standalone remote microservice independence of the core engine to get **instant in-process testability, zero IPC overhead, thin and decoupled interfaces, and strict architectural enforcement**.

## Revisit when
Core retrieval needs to scale horizontally across a distributed compute cluster separate from the interface hosts.
