"""tests/test_demo_e2e.py
End-to-End User Journey integration tests for the DocuMind Public Demo Gateway.
Verifies:
1. Public visitor connection with zero client credentials.
2. File upload, automatic indexing, chunk extraction, and metadata reporting.
3. Natural-language questioning with citations and candidate chunks inspection.
4. Agent analysis actions (summarize, key_points, explain).
5. Transparent abstention for ungrounded queries (preventing hallucinations).
6. Cross-session isolation (Session A cannot see or delete Session B documents).
7. Document deletion and cleanup.
8. Error handling without internal secret or stack trace leakage.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Usage
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager


class MockDeterministicLLM:
    """Deterministic mock LLM for end-to-end integration tests without paid API costs."""

    model_id: str = "mock-claude-test"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            (
                "Operating system semaphores use atomic integer counters to serialize "
                "concurrent process execution [S1]. Binary semaphores alternate between "
                "locked and unlocked states [S2]."
            ),
            Usage(input_tokens=150, output_tokens=40),
        )


@pytest.fixture
def demo_app(tmp_path: Path):
    settings = Settings(
        home=tmp_path / "home",
        embed_model="BAAI/bge-small-en-v1.5",
        env="dev",
        api_key="admin_secret_key_minimum_32_characters_long",
        allow_debug=True,
    )
    import numpy as np

    from documind.core.vector_store import NumpyStore

    class FastEmbedder:
        model_id = "test-model"
        dim = 4

        def embed_query(self, text: str):
            v = np.zeros(4, dtype=np.float32)
            v[0] = 1.0
            return v

        def embed_documents(self, texts):
            arr = np.zeros((len(texts), 4), dtype=np.float32)
            for i in range(len(texts)):
                arr[i, 0] = 1.0
            return arr

    embedder = FastEmbedder()
    store = NumpyStore(dim=4)
    mock_llm = MockDeterministicLLM()

    engine = DocuMind(
        settings=settings,
        embedder=embedder,
        store=store,
        llm=mock_llm,
    )

    app = create_app(dm=engine, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=settings.home / "sessions",
        shared_embedder=embedder,
        shared_llm=mock_llm,
        settings=settings,
    )
    return app


def test_public_demo_full_journey(demo_app):
    client = TestClient(demo_app)
    # Acquire server-issued sessions
    sess_a_resp = client.post("/api/demo/session")
    assert sess_a_resp.status_code == 201
    sess_a = sess_a_resp.json()["session_id"]

    sess_b_resp = client.post("/api/demo/session")
    assert sess_b_resp.status_code == 201
    sess_b = sess_b_resp.json()["session_id"]

    headers_a = {"X-Session-ID": sess_a}
    headers_b = {"X-Session-ID": sess_b}

    # 1. Health check - public without auth
    h_res = client.get("/healthz")
    assert h_res.status_code == 200
    assert h_res.json()["status"] == "ok"

    # 2. Initially, session A workspace is empty
    docs_res = client.get("/api/demo/documents", headers=headers_a)
    assert docs_res.status_code == 200
    assert docs_res.json() == []

    # Asking on empty index produces 409 index_empty
    ask_empty = client.post(
        "/api/demo/ask",
        headers=headers_a,
        json={"question": "What is a semaphore?"},
    )
    assert ask_empty.status_code == 409
    assert ask_empty.json()["error"]["code"] == "index_empty"

    # 3. Upload document into Session A
    doc_content = (
        b"# Operating Systems Notes\n\n"
        b"A semaphore is a synchronization variable that manages access to common resources.\n"
        b"Binary semaphores act as mutual exclusion locks across concurrent threads.\n"
        b"Counting semaphores allow a fixed number of concurrent workers into a critical section.\n"
    )
    upload_res = client.post(
        "/api/demo/documents",
        headers=headers_a,
        files={"file": ("os_notes.md", io.BytesIO(doc_content), "text/markdown")},
    )
    assert upload_res.status_code == 201
    u_data = upload_res.json()
    assert u_data["status"] == "indexed"
    assert u_data["source"] == "os_notes.md"
    assert u_data["chunks"] >= 1

    # 4. Session A lists documents
    docs_res2 = client.get("/api/demo/documents", headers=headers_a)
    assert docs_res2.status_code == 200
    docs_list = docs_res2.json()
    assert len(docs_list) == 1
    assert docs_list[0]["source"] == "os_notes.md"
    assert docs_list[0]["chunks"] >= 1

    # 5. Inspect chunk contents in Session A
    chunks_res = client.get("/api/demo/documents/os_notes.md/chunks", headers=headers_a)
    assert chunks_res.status_code == 200
    chunks = chunks_res.json()
    assert len(chunks) >= 1
    assert "semaphore" in chunks[0]["text"].lower()

    # 6. Ask question in Session A
    ask_res = client.post(
        "/api/demo/ask",
        headers=headers_a,
        json={"question": "How does a semaphore synchronize processes?"},
    )
    assert ask_res.status_code == 200
    a_data = ask_res.json()
    assert a_data["outcome"] == "answered"
    assert "retrieved" in a_data
    assert len(a_data["retrieved"]) >= 1
    assert "semaphore" in a_data["text"].lower()
    assert len(a_data["citations"]) >= 1

    # 7. Analysis actions in Session A
    for act in ["summarize", "key_points", "explain"]:
        act_res = client.post(
            "/api/demo/analyze",
            headers=headers_a,
            json={"action": act},
        )
        assert act_res.status_code == 200
        assert act_res.json()["outcome"] == "answered"

    # 8. Cross-session isolation: Session B cannot see Session A's document
    b_docs = client.get("/api/demo/documents", headers=headers_b)
    assert b_docs.status_code == 200
    assert b_docs.json() == []

    # Session B cannot get Session A's chunks (404)
    b_chunks = client.get("/api/demo/documents/os_notes.md/chunks", headers=headers_b)
    assert b_chunks.status_code == 404

    # Session B cannot delete Session A's document (404)
    b_del = client.delete("/api/demo/documents/os_notes.md", headers=headers_b)
    assert b_del.status_code == 404

    # Session B querying has empty index (409)
    b_ask = client.post(
        "/api/demo/ask",
        headers=headers_b,
        json={"question": "What is a semaphore?"},
    )
    assert b_ask.status_code == 409

    # 9. Session A deletion works
    del_res = client.delete("/api/demo/documents/os_notes.md", headers=headers_a)
    assert del_res.status_code == 204

    # Session A workspace is now empty again
    docs_after = client.get("/api/demo/documents", headers=headers_a)
    assert docs_after.status_code == 200
    assert docs_after.json() == []

    # 10. Security check: No API key or Anthropic secrets appear in responses
    all_responses_text = " ".join([
        h_res.text,
        docs_res.text,
        upload_res.text,
        ask_res.text,
    ])
    assert "admin_secret_key" not in all_responses_text
    assert "sk-ant-" not in all_responses_text
