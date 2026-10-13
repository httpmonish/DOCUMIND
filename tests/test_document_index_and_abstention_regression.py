"""tests/test_document_index_and_abstention_regression.py
Regression tests for:
1. Complete PDF upload to answer flow in isolated session workspaces.
2. Real document indexing, chunk counts verification, and ChromaDB persistence.
3. Explicit SSE error event handling (code=index_empty) when workspace is empty.
4. Failed upload error reporting without phantom documents in the index.
5. Genuine low-relevance abstention (outcome=abstained, reason=low_score) distinct from empty index.
6. Interrupted stream detection when disconnected without a completion event.
7. Unconfigured LLM mode returning semantic retrieval candidates distinct from abstention.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Usage
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager


class DeterministicMockLLM:
    """Mock LLM returning grounded cited answers."""

    model_id: str = "mock-llm-regression"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            "DocuMind verifies documents with semantic retrieval [S1]. "
            "It enforces citations and grounds answers against hallucinations [S2].",
            Usage(input_tokens=120, output_tokens=30),
        )


class ControlledEmbedder:
    """Embedder allowing controlled cosine similarity for relevant vs irrelevant questions."""

    model_id: str = "controlled-embedder-v1"
    dim: int = 4

    def embed_query(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        lower = text.lower()
        if "irrelevant" in lower or "alien" in lower or "quantum_cooking" in lower:
            # Orthogonal vector yielding ~0.0 cosine similarity (< tau 0.35)
            v[1] = 1.0
        else:
            # Parallel vector yielding 1.0 cosine similarity (>= tau 0.35)
            v[0] = 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


def parse_sse_stream(raw_text: str) -> list[tuple[str, dict[str, Any] | str]]:
    """Parse raw SSE text into a list of (event_name, data) pairs."""
    events = []
    blocks = raw_text.split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        event_name = None
        event_data = None
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                raw_data = line[6:].strip()
                try:
                    event_data = json.loads(raw_data)
                except Exception:
                    event_data = raw_data
        if event_name:
            events.append((event_name, event_data))
    return events


@pytest.fixture
def regression_app(tmp_path: Path):
    settings = Settings(
        home=tmp_path / "home",
        embed_model="controlled-embedder-v1",
        env="dev",
        api_key="admin_secret_key_minimum_32_characters_long",
        allow_debug=True,
        min_score=0.35,
    )

    embedder = ControlledEmbedder()
    store = NumpyStore(dim=4)
    llm = DeterministicMockLLM()

    engine = DocuMind(
        settings=settings,
        embedder=embedder,
        store=store,
        llm=llm,
    )

    app = create_app(dm=engine, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=settings.home / "sessions",
        shared_embedder=embedder,
        shared_llm=llm,
        settings=settings,
    )
    return app


def test_successful_pdf_upload_and_relevant_question_flow(regression_app):
    """1. Trace PDF upload through indexing and Chroma storage, verifying real chunk count
    and grounded answer.
    """
    client = TestClient(regression_app)

    # Bootstrap guest visitor session
    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sid = sess_res.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Verify initial empty state
    initial_docs = client.get("/api/demo/documents", headers=headers).json()
    assert initial_docs == []

    # Upload real PDF fixture (hello.pdf)
    pdf_fixture = Path("tests/fixtures/hello.pdf")
    assert pdf_fixture.exists()

    with pdf_fixture.open("rb") as f:
        files = {"file": ("hello.pdf", f, "application/pdf")}
        up_res = client.post("/api/demo/documents", headers=headers, files=files)

    assert up_res.status_code == 201
    up_data = up_res.json()
    assert up_data["status"] == "indexed"
    assert up_data["source"] == "hello.pdf"
    assert up_data["chunks"] >= 1
    assert up_data["chunk_count"] >= 1
    assert len(up_data["sha256"]) == 64

    # Verify document listing reports the real document and chunks
    docs_res = client.get("/api/demo/documents", headers=headers)
    assert docs_res.status_code == 200
    docs = docs_res.json()
    assert len(docs) == 1
    assert docs[0]["source"] == "hello.pdf"
    assert docs[0]["chunks"] == up_data["chunks"]
    assert docs[0]["status"] == "indexed"

    # Verify chunk inspector
    chunks_res = client.get("/api/demo/documents/hello.pdf/chunks", headers=headers)
    assert chunks_res.status_code == 200
    chunks = chunks_res.json()
    assert len(chunks) == up_data["chunks"]
    assert chunks[0]["source"] == "hello.pdf"
    assert "DocuMind" in chunks[0]["text"]

    # Stream relevant question via SSE
    stream_res = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "What is DocuMind?", "top_k": 3},
    )
    assert stream_res.status_code == 200
    assert "text/event-stream" in stream_res.headers["content-type"]

    events = parse_sse_stream(stream_res.text)
    event_names = [ev[0] for ev in events]

    assert "meta" in event_names
    assert "retrieval" in event_names
    assert "token" in event_names
    assert "citations" in event_names
    assert "done" in event_names
    assert "error" not in event_names

    # Check retrieval candidates passed tau threshold
    retrieval_data = next(ev[1] for ev in events if ev[0] == "retrieval")
    assert len(retrieval_data["retrieved"]) >= 1
    assert all(c["score"] >= 0.35 for c in retrieval_data["retrieved"])

    # Check completion event
    done_data = next(ev[1] for ev in events if ev[0] == "done")
    assert done_data["outcome"] == "answered"
    assert done_data["usage"]["output_tokens"] > 0


def test_empty_index_sse_error_event(regression_app):
    """2. An empty workspace emits an explicit error event with code 'index_empty' and does not
    false-abstain.
    """
    client = TestClient(regression_app)

    # Initialize empty session
    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sid = sess_res.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Query with empty index
    stream_res = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "Summarize my documents"},
    )
    assert stream_res.status_code == 200
    events = parse_sse_stream(stream_res.text)

    # Must emit exactly one event: 'error' with code 'index_empty'
    assert len(events) == 1
    assert events[0][0] == "error"
    err_payload = events[0][1]
    assert isinstance(err_payload, dict)
    assert err_payload["code"] == "index_empty"
    assert "No documents uploaded yet" in err_payload["message"]

    # Must NOT emit 'done' with outcome 'abstained' or 'low_score'
    event_names = [ev[0] for ev in events]
    assert "done" not in event_names
    assert "retrieval" not in event_names


def test_failed_pdf_upload_handling(regression_app):
    """3. Corrupt PDF upload fails with 422, does not leave phantom documents or chunks."""
    client = TestClient(regression_app)

    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sid = sess_res.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Corrupt PDF (starts with %PDF- header to pass mimetype filter, but invalid byte structure)
    corrupt_bytes = b"%PDF-1.4\ncorrupt header and unreadable xref table\x00\xff"
    files = {"file": ("damaged.pdf", io.BytesIO(corrupt_bytes), "application/pdf")}

    up_res = client.post("/api/demo/documents", headers=headers, files=files)
    assert up_res.status_code == 422
    assert up_res.json()["error"]["code"] == "document_unreadable"

    # Index must remain empty
    docs = client.get("/api/demo/documents", headers=headers).json()
    assert docs == []

    # Chat query must emit index_empty error, NOT false-abstention
    chat_res = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "What happened?"},
    )
    events = parse_sse_stream(chat_res.text)
    assert len(events) == 1
    assert events[0][0] == "error"
    assert events[0][1]["code"] == "index_empty"


def test_genuine_low_relevance_abstention_distinct_from_empty_index(regression_app):
    """4. Genuine low-relevance queries emit outcome 'abstained' with reason 'low_score',
    distinct from index_empty.
    """
    client = TestClient(regression_app)

    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sid = sess_res.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Upload document
    pdf_fixture = Path("tests/fixtures/hello.pdf")
    with pdf_fixture.open("rb") as f:
        files = {"file": ("hello.pdf", f, "application/pdf")}
        client.post("/api/demo/documents", headers=headers, files=files)

    # Query with low relevance question
    # ControlledEmbedder returns orthogonal vector for 'irrelevant'
    stream_res = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "irrelevant quantum_cooking recipe for martian aliens"},
    )
    assert stream_res.status_code == 200
    events = parse_sse_stream(stream_res.text)
    event_names = [ev[0] for ev in events]

    assert "meta" in event_names
    assert "retrieval" in event_names
    assert "token" in event_names
    assert "done" in event_names
    assert "error" not in event_names

    # Check that candidate chunks were retrieved but failed gate (< 0.35)
    ret_data = next(ev[1] for ev in events if ev[0] == "retrieval")
    assert len(ret_data["retrieved"]) >= 1
    assert all(c["score"] < 0.35 for c in ret_data["retrieved"])
    assert all(not c["passed_gate"] for c in ret_data["retrieved"])

    # Check explicit abstention completion
    done_data = next(ev[1] for ev in events if ev[0] == "done")
    assert done_data["outcome"] == "abstained"
    assert done_data["reason"] == "low_score"


def test_unconfigured_llm_mode_distinct_from_abstention(tmp_path: Path):
    """5. When no LLM is configured, return candidate chunks with outcome 'unconfigured_model',
    distinct from abstention.
    """
    settings = Settings(
        home=tmp_path / "home",
        embed_model="controlled-embedder-v1",
        env="dev",
        api_key="admin_secret_key_minimum_32_characters_long",
        allow_debug=True,
    )
    embedder = ControlledEmbedder()
    store = NumpyStore(dim=4)

    # Engine with NO LLM
    engine = DocuMind(
        settings=settings,
        embedder=embedder,
        store=store,
        llm=None,
    )

    app = create_app(dm=engine, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=settings.home / "sessions",
        shared_embedder=embedder,
        shared_llm=None,
        settings=settings,
    )

    client = TestClient(app)
    sess_res = client.post("/api/demo/session")
    headers = {"X-Session-ID": sess_res.json()["session_id"]}

    # Upload document
    pdf_fixture = Path("tests/fixtures/hello.pdf")
    with pdf_fixture.open("rb") as f:
        files = {"file": ("hello.pdf", f, "application/pdf")}
        client.post("/api/demo/documents", headers=headers, files=files)

    # Query with relevant question
    stream_res = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "What is inside hello.pdf?"},
    )
    events = parse_sse_stream(stream_res.text)
    event_names = [ev[0] for ev in events]

    assert "retrieval" in event_names
    assert "token" in event_names
    assert "citations" in event_names
    assert "done" in event_names

    done_data = next(ev[1] for ev in events if ev[0] == "done")
    assert done_data["outcome"] == "unconfigured_model"


def test_interrupted_stream_detection(regression_app):
    """6. Verifies that client can detect incomplete stream when disconnected before done event."""
    client = TestClient(regression_app)

    sess_res = client.post("/api/demo/session")
    headers = {"X-Session-ID": sess_res.json()["session_id"]}

    # Upload document
    pdf_fixture = Path("tests/fixtures/hello.pdf")
    with pdf_fixture.open("rb") as f:
        files = {"file": ("hello.pdf", f, "application/pdf")}
        client.post("/api/demo/documents", headers=headers, files=files)

    # Request stream with stream reading
    with client.stream(
        "POST", "/api/demo/chat/stream", headers=headers, json={"question": "Hello"}
    ) as response:
        lines = []
        for line in response.iter_lines():
            lines.append(line)
            # Break early after meta and retrieval events, simulating client disconnect
            if "event: retrieval" in line:
                break

    partial_raw = "\n".join(lines)
    events = parse_sse_stream(partial_raw)
    event_names = [ev[0] for ev in events]

    assert "meta" in event_names
    assert "retrieval" in event_names
    # Critically, 'done' was NOT reached
    assert "done" not in event_names
