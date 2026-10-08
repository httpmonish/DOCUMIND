# 0005. Core Engine and Interface Split

## Context
DocuMind supports three consumer interfaces: CLI, FastAPI REST service, and an MCP server for Claude Desktop. Code must remain maintainable with zero duplication across interfaces.

## Options with numbers
1. **REST-first (CLI and MCP call a running HTTP server)**:
   - Requires a daemon server continuously running.
   - IPC latency: adds 5–20 ms per request.
   - High debugging complexity when testing retrieval core in unit tests.
2. **Framework Monolith (LangChain / LlamaIndex)**:
   - Enormous dependency footprint (>50 transitive packages, >500 MB).
   - Tightly couples retrieval logic to proprietary framework abstractions.
3. **Pure Core Library + Thin Adapters** (Chosen):
   - `documind/core/` is a pure Python library that imports zero interface frameworks (`fastapi`, `mcp`, `argparse`, `click`).
   - Zero IPC overhead for CLI and MCP.
   - AST-based architecture guard (`tests/test_architecture.py`) statically enforces zero leakage.

## Decision
Keep `documind/core/` completely pure. All interface adapters (`cli.py`, `api.py`, `mcp_server.py`) import from core, but core never imports from interfaces. Phase 1 scripts live in `scripts/`.

## You give up X to get Y
You give up standalone remote microservice independence of the core engine to get **instant in-process testability, zero IPC overhead, and clean separation of concerns**.

## Revisit when
Core retrieval needs to scale horizontally across a separate compute cluster from the interface hosts.
