# DocuMind — API Specification & Integration Contract

**Document Version:** 1.0.0  
**Status:** Canonical Reference  
**Last Updated:** 2026-10-10  

---

## 1. Overview & Authentication Boundaries

DocuMind provides two distinct API interfaces:
1. **Administrative / Core Service API (`/v1/*`):** Requires `X-API-Key: <DOCUMIND_API_KEY>` (minimum 32 characters, constant-time `hmac.compare_digest` check). Intended for trusted backend microservices, scripts, and direct programmatic integrations.
2. **Public Live Demo Gateway (`/api/demo/*`):** Zero API key required from browser visitors. All operations are scoped to an opaque session identifier provided via `X-Session-ID: <session_id>` (16 to 64 alphanumeric characters, hyphens, and underscores). Each session operates in strict tenant isolation.

---

## 2. Common Standards

### Headers
| Header | Description | Required By |
|---|---|---|
| `X-API-Key` | 32+ character administrative key | All `/v1/*` endpoints |
| `X-Session-ID` | Opaque visitor session token (`^[a-zA-Z0-9_-]{16,64}$`) | All `/api/demo/*` endpoints |
| `X-Request-ID` | Correlated request tracking ID (returned on all responses) | Client (optional) / Server (emitted) |

### Error Envelope
All non-2xx error responses follow a uniform JSON structure:
```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable explanation of error.",
    "request_id": "4b68e987-9811-42e7-8f55-12e0e4b85c21"
  }
}
```

Standard error codes:
- `unauthorized` (401): Missing or invalid `X-API-Key`.
- `invalid_session` (400): Malformed `X-Session-ID`.
- `rate_limited` (429): Token bucket capacity exceeded.
- `document_unreadable` (422): Document text cannot be parsed.
- `document_too_large` (413): Document exceeds `DOCUMIND_MAX_UPLOAD_MB` or page cap.
- `conflict` (409): Document already exists with identical checksum.
- `not_found` (404): Requested document or resource does not exist.
- `index_unavailable` (503): Vector store indexing failed.
- `llm_unavailable` (502): External language model unavailable.
- `internal_error` (500): Server-side unexpected exception.

---

## 3. Endpoints

### 3.1 Health Check (Public)
- **Path:** `GET /healthz`
- **Auth:** None
- **Response `200 OK`:**
  ```json
  {
    "status": "ok",
    "index_chunks": 12,
    "embed_model": "BAAI/bge-small-en-v1.5",
    "schema_version": 1,
    "tau": 0.35
  }
  ```

---

### 3.2 Public Demo Gateway Endpoints (`/api/demo/*`)

#### 3.2.1 Acquire Visitor Session
- **Path:** `POST /api/demo/session`
- **Auth:** None (Public)
- **Response `201 Created`:**
  ```json
  {
    "session_id": "949a699b56a40c113b45340115b4c68eef4d9309ba1f7e1314683cedea1ec1ae",
    "expires_at": 1792440000.0,
    "ttl_seconds": 86400
  }
  ```
- **Error `401 Unauthorized`:** If an expired or forged session token is passed in subsequent calls.

#### 3.2.2 Upload & Ingest Document
- **Path:** `POST /api/demo/documents`
- **Auth:** `X-Session-ID: <session_id>`
- **Content-Type:** `multipart/form-data`
- **Form Parameters:**
  - `file`: Binary file data (`.pdf`, `.txt`, `.md`, max 10 MB streaming abort)
  - `replace`: `boolean` (optional, default: `false`)
- **Quota Enforced:** Max 5 documents and 20 MB total per session.
- **Response `200 OK`:**
  ```json
  {
    "status": "indexed",
    "source": "os_lecture.pdf",
    "chunks": 9,
    "sha256": "949a699b56a40c113b45340115b4c68eef4d9309ba1f7e1314683cedea1ec1ae"
  }
  ```

#### 3.2.3 List Session Documents
- **Path:** `GET /api/demo/documents`
- **Auth:** `X-Session-ID: <session_id>`
- **Response `200 OK`:**
  ```json
  [
    {
      "source": "os_lecture.pdf",
      "chunks": 9,
      "sha256": "949a699b56a40c113b45340115b4c68eef4d9309ba1f7e1314683cedea1ec1ae"
    }
  ]
  ```

#### 3.2.4 Inspect Document Chunks
- **Path:** `GET /api/demo/documents/{source}/chunks`
- **Auth:** `X-Session-ID: <session_id>`
- **Response `200 OK`:** List of chunks with `id`, `text`, `chunk_index`.

#### 3.2.5 Delete Document
- **Path:** `DELETE /api/demo/documents/{source}`
- **Auth:** `X-Session-ID: <session_id>`
- **Response `204 No Content`**
- **Error `404 Not Found`:** If document does not exist in this session.

#### 3.2.6 Ask Grounded Question
- **Path:** `POST /api/demo/ask`
- **Auth:** `X-Session-ID: <session_id>`
- **Content-Type:** `application/json`
- **Request Body:**
  ```json
  {
    "question": "What is process scheduling in the kernel?",
    "top_k": 5
  }
  ```
- **Response `200 OK (Answered)`:**
  ```json
  {
    "text": "Process scheduling allocates execution intervals among active processes. [S1]",
    "outcome": "answered",
    "abstain_reason": null,
    "citations": [
      {
        "marker": "S1",
        "source": "os_lecture.pdf",
        "chunk_index": 0,
        "snippet": "Process scheduling is the mechanism by which the kernel...",
        "score": 0.8142
      }
    ],
    "model": "claude-haiku-4-5-20251001",
    "usage": { "input_tokens": 1200, "output_tokens": 150 },
    "latency_ms": 1150
  }
  ```

#### 3.2.7 Multi-Turn Chat (`POST /api/demo/chat`)
- **Path:** `POST /api/demo/chat`
- **Auth:** `X-Session-ID: <session_id>`
- **Content-Type:** `application/json`
- **Request Body:**
  ```json
  {
    "question": "how does it work?",
    "conversation_id": "c7a82b9e-64d8-4f27-a0e2-63b75c12e091",
    "top_k": 5
  }
  ```
- **Behavior:** Condenses anaphora/follow-up questions using conversation turn context, expands neighbor chunks for top-2 hits, and persists turns in SQLite.
- **Response `200 OK`:** Returns answer envelope with `conversation_id`, `condensed_query`, and `message_id`.

#### 3.2.8 Server-Sent Events (SSE) Streaming Chat (`POST /api/demo/chat/stream`)
- **Path:** `POST /api/demo/chat/stream`
- **Auth:** `X-Session-ID: <session_id>`
- **Content-Type:** `application/json`
- **Response:** `text/event-stream`
- **Event Flow:**
  1. `event: meta` — `data: {"conversation_id": "...", "query": "...", "condensed_query": "...", "tau": 0.35, "request_id": "..."}`
  2. `event: retrieval` — `data: {"retrieved": [{"id": "...", "source": "...", "score": 0.82, "passed_gate": true}, ...]}` (immediate Glass Box inspector update)
  3. `event: token` — `data: {"delta": "word "}` (streamed real-time tokens)
  4. `event: citations` — `data: {"citations": [{"marker": "S1", "source": "...", "score": 0.82}, ...]}`
  5. `event: done` — `data: {"outcome": "answered", "latency_ms": 1120, "usage": {"input_tokens": 1400, "output_tokens": 85, "cost_usd": 0.0019}}`

#### 3.2.9 Conversation Thread Management
- **List Threads:** `GET /api/demo/conversations`
- **Get Messages:** `GET /api/demo/conversations/{id}/messages`
- **Delete Thread:** `DELETE /api/demo/conversations/{id}`

#### 3.2.10 Analysis Actions
- **Path:** `POST /api/demo/analyze`
- **Actions:** `summarize`, `key_points`, `explain`.

#### 3.2.11 Spend Capping & Rate Limiting
- **Spend Ceiling:** Global $2.00/day, per-IP $0.25/day (Claude Haiku 4.5 pricing). When cap is hit, endpoints gracefully fail closed to `retrieval_only` with 0 HTTP 500 errors.
- **Sliding Window Rate Limits:** 60 req/min general, 10 req/min questions, 5/hr uploads, 5/hr sessions. IPv6 addresses are normalized to `/64` subnets.
- **Security Headers:** `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy`.

---

## 4. Administrative Core Endpoints (`/v1/*`)

The `/v1` endpoints mirror core operations for administrative clients:
- `POST /v1/documents`
- `GET /v1/documents`
- `DELETE /v1/documents/{source}`
- `GET /v1/documents/{source}/chunks`
- `POST /v1/ask`
- `GET /v1/events`
- `GET /v1/eval`
- `GET /v1/meta`

All require `X-API-Key: <DOCUMIND_API_KEY>` (32+ characters).
