# DocuMind Model Context Protocol (MCP) Server (v0.7.0)

DocuMind provides a secure, read-only MCP server allowing desktop AI assistants—such as **Claude Desktop** and **Claude Code**—to perform grounded semantic search over your private local document index.

The server operates on **retrieval-only**: it performs zero LLM generations, requires zero API keys, makes zero network requests, and communicates strictly over **standard I/O (`stdio`)**. The connected desktop client reads the retrieved, cited passages and writes the response using its own model.

---

## Tools Reference

All tools are annotated with `readOnlyHint=True`, `destructiveHint=False`, `idempotentHint=True`, and `openWorldHint=False`.

| Tool Name | Parameters | Return Values | Description |
| :--- | :--- | :--- | :--- |
| `search_documents` | `query: str` (1–2000 chars)<br>`top_k: int = 5` (1–10)<br>`document: str \| None` | `outcome`: `"results"` \| `"no_relevant_results"` \| `"empty_index"`<br>`threshold`: float (tau gate)<br>`top_score`: float \| null<br>`results`: list of cited chunks<br>`notice`: str<br>`truncated`: bool | Executes semantic search across local documents with relevance confidence gating ($\tau = 0.35$). Returns cited chunks labeled `[S1]`, `[S2]`, etc. |
| `get_chunk` | `chunk_id: str`<br>`neighbors: int = 1` (0–3) | `chunk_id`: str<br>`doc_id`: str<br>`source`: str (basename)<br>`chunk_index`: int<br>`text`: str<br>`neighbors`: list of neighbor chunks<br>`truncated`: bool | Fetches an exact chunk plus adjacent predecessor and successor chunks for wider paragraph context. |
| `list_documents` | *(None)* | `documents`: list of `{doc_id, source, chunk_count, indexed_at, content_hash}`<br>`count`: int | Lists all indexed files in the primary index with their chunk counts and short SHA-256 digests. |
| `index_info` | *(None)* | `document_count`: int<br>`chunk_count`: int<br>`embedder_name`: str<br>`dimensions`: int<br>`tau`: float<br>`store_type`: str<br>`documind_version`: str | Returns high-level metadata and capacity statistics for the active index. |

---

## Resources and Prompts

- **Resources**:
  - `documind://index/info`: Read-only JSON resource containing index configuration and statistics.
  - `documind://chunk/{chunk_id}`: Read-only JSON resource containing an individual chunk's text and metadata.
- **Prompts**:
  - `answer_from_documents(question)`: Preconfigured prompt directing the client model to call `search_documents`, answer strictly using returned passages, cite `[S1]`, `[S2]`, and abstain if `outcome` is `no_relevant_results`.

---

## Security Model

1. **Read-Only Invariant**: The MCP server contains no endpoints or tools to index, upload, edit, or delete documents.
2. **Untrusted Data Sanitization**:
   - All document text and filenames are treated as untrusted data.
   - Non-printable ASCII/Unicode control characters are stripped.
   - Unicode bidirectional (bidi) override characters (`\u202a`–`\u202e`, `\u2066`–`\u2069`) are stripped.
   - In-document citation markers (`[S<n>]`) are neutralized to `[S <n>]` to prevent citation spoofing.
   - Prompt injection delimiter tags (`<|im_end|>`, `<|im_start|>`) are neutralized.
3. **Information Disclosure Prevention**:
   - The server never emits absolute filesystem paths, operating system usernames, environment variables, or Python stack traces.
   - Document sources are stripped to their basename (e.g. `guide.pdf`).
4. **Storage Isolation**:
   - The server serves **only** the primary administrative index under `DOCUMIND_HOME`.
   - Access to transient web or demo session workspaces (`sessions/*`) is strictly forbidden and rejected at startup.
5. **Stdio Purity**:
   - Standard output (`stdout`) belongs exclusively to the JSON-RPC framing protocol.
   - All diagnostic and operational logs are routed to `stderr`. Python `print()` is strictly banned (`ruff T201`).
   - Logging operates at `INFO` level and never records query text, chunk contents, or credentials.
6. **Response Size Capping**:
   - Total response characters are capped to 20,000 characters by default (configurable via `DOCUMIND_MCP_MAX_RESPONSE_CHARS`).
   - Oversized responses are truncated gracefully with an explicit `truncated: true` flag.
7. **Zero Network / Shell**:
   - The server module does not import `socket`, `requests`, `httpx`, `urllib3`, or `subprocess`.

---

## Setup Instructions

### 1. Claude Desktop Setup

To configure DocuMind in Claude Desktop:

1. Obtain your verified machine launch configuration:
   ```bash
   documind mcp config
   ```
2. Open your Claude Desktop configuration file on macOS:
   ```bash
   ~/Library/Application Support/Claude/claude_desktop_config.json
   ```
3. Add the `documind` server under `mcpServers`:
   ```json
   {
     "mcpServers": {
       "documind": {
         "command": "/ABSOLUTE/PATH/TO/PYTHON",
         "args": ["-m", "documind.interfaces.cli", "mcp", "serve"],
         "env": {
           "DOCUMIND_HOME": "/Users/USERNAME/.documind"
         }
       }
     }
   }
   ```
4. Restart Claude Desktop. A hammer icon will appear in the lower right corner indicating connected MCP tools.

### 2. Claude Code Setup

Run the following command in your terminal:
```bash
claude mcp add documind -e DOCUMIND_HOME="/Users/USERNAME/.documind" -- "/ABSOLUTE/PATH/TO/PYTHON" -m documind.interfaces.cli mcp serve
```

---

## Troubleshooting

- **Server does not appear in Claude Desktop**:
  - Verify that the path in `command` points to an absolute Python executable within a virtual environment where `documind[mcp]` is installed.
  - Check Claude Desktop logs on macOS at:
    ```bash
    ~/Library/Logs/Claude/mcp.log
    ~/Library/Logs/Claude/main.log
    ```
- **Handshake Timeout**:
  - The DocuMind MCP server utilizes lazy loading to answer the `initialize` handshake in under 250ms without loading PyTorch or embedding models. If Claude Desktop times out, verify your Python virtual environment is not corrupted.
- **Empty Index or Missing Index**:
  - If `DOCUMIND_HOME` contains no index, the server will log an error to `stderr` and fail fast with exit code 6.
  - Run `documind index <path_to_documents>` to populate your index before launching the MCP server.
- **Wrong DOCUMIND_HOME**:
  - Claude Desktop launches processes with a minimal environment. Always specify `DOCUMIND_HOME` explicitly in the `env` dictionary of `claude_desktop_config.json`.
- **Diagnostic Verification**:
  - Run the diagnostic doctor check:
    ```bash
    documind doctor
    ```
    Ensure `[ok] mcp sdk`, `[ok] mcp index`, and `[ok] mcp model cache` are reported.

---

## Explicitly Unsupported Features

The DocuMind MCP server is intentionally scoped for security and local-first reliability. The following are explicitly **not supported**:
1. **Remote / HTTP / SSE Transport**: The server only operates over local `stdio`.
2. **Write / Modification Tools**: No document uploads, indexing, updates, or deletions are exposed over MCP.
3. **Answer Generation / LLM Calling**: The server does not execute internal LLM completions. The client LLM generates answers from retrieved evidence chunks.
