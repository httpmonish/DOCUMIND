# ADR 0010: Secure, Read-Only Model Context Protocol (MCP) Server

## Context
DocuMind requires standard interoperability with external desktop AI agents and assistants (such as Anthropic Claude Desktop and Claude Code CLI). Users want their local LLM clients to discover, search, and cite their private indexed documents directly within conversational workflows without sending private indexes to third-party cloud vector databases.

However, running an in-process or local agent server introduces significant attack surface and reliability constraints:
1. **Security & Sandboxing**: Untrusted document chunks must not trick client LLMs into running malicious tool calls or prompt injection.
2. **Standard I/O Discipline**: In stdio transport, stdout is strictly reserved for JSON-RPC frames. Any unexpected stdout write breaks protocol framing.
3. **Low Latency Handshake**: Desktop clients enforce strict initialization timeouts (often <2 seconds). Loading dense embedding models (like BGE-small) at process boot causes connection timeouts.
4. **Data Isolation**: The MCP server must serve only the user's primary CLI index and strictly forbid access to transient demo or web sessions (`sessions/*`).

## Options Considered

1. **HTTP/SSE Transport with Bi-directional Tooling (Read & Write)**
   - Allows network access and indexing via MCP.
   - *Rejected*: Massive attack surface; exposed port allows cross-origin or local SSRF attacks; writing/indexing from desktop clients risks race conditions and data corruption.

2. **Full QA Engine via MCP (`ask` Tool invoking DocuMind internal LLM)**
   - The MCP tool calls an internal LLM (Anthropic/OpenAI) and returns synthesized answers.
   - *Rejected*: Redundant and costly. The MCP client (Claude) is already a state-of-the-art reasoning model. Returning raw cited passages allows Claude to synthesize the response natively without secondary API keys, extra billing, or network overhead.

3. **Stdio-Only, Retrieval-Only, Read-Only FastMCP Server (Chosen)**
   - Transport: Standard I/O (stdio) only. Zero network ports opened.
   - Operations: Strictly read-only (`readOnlyHint=True`, `destructiveHint=False`).
   - Retrieval only: No internal LLM calls or API keys required.
   - SDK: Official `mcp` SDK pinned to 1.x (`mcp>=1.29.0,<2`), avoiding unstable v2 alpha breaking changes.
   - Architecture: Lazy initialization on first tool call; stdio redirection during imports; multi-layer sanitization of chunk texts.

## Decision

We implement a dedicated, secure MCP server in `documind.interfaces.mcp_server` exposed via `documind mcp serve` and `documind mcp config`.

Key architectural choices:
- **FastMCP 1.x SDK Pinning**: Pinned to `mcp>=1.29.0,<2` within an optional `[mcp]` extra. Core installs incur zero added dependencies.
- **Stdio Transport Exclusivity**: Zero HTTP/SSE endpoints. Logging is directed strictly to `stderr` via `logging.getLogger("documind.mcp")`. `print()` is statically banned via Ruff rule `T201` and AST tests.
- **Lazy Engine Loading**: FastMCP server responds to the `initialize` handshake in under 250ms without loading PyTorch or SentenceTransformers. Engine and embedders load on first tool execution under a thread-safe mutex lock.
- **Strict Data Isolation**: Explicit check verifies that `DOCUMIND_HOME` and storage paths are never inside `sessions/*`.
- **Untrusted Content Sanitization**: Control characters and Unicode bidi overrides are stripped. Delimiters (including `[S<n>]` patterns and prompt injection tags) are neutralized to prevent citation spoofing and prompt extraction.
- **Response Size Capping**: Response size is capped to 20,000 characters (configurable via `DOCUMIND_MCP_MAX_RESPONSE_CHARS`) with an explicit `truncated: true` flag.

## Trade-offs: You Give Up X to Get Y
- **You give up:** Document upload, deletion, and remote HTTP server capabilities over MCP.
- **To get:** Bulletproof security isolation, zero network attack surface, sub-250ms desktop client startup, and pure zero-key retrieval.

## Revisit When
Revisit if the Model Context Protocol finalizes an official authenticated local unix domain socket transport or if client authentication standards emerge that allow safe multi-user multi-workspace serving.
