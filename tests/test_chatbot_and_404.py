"""tests/test_chatbot_and_404.py
Verification tests for:
1. Static 404 page serving with content negotiation (HTML vs JSON).
2. Clean reference Chatbot UI mounting at /app/chat.html.
3. Conversation deletion endpoint and tenant isolation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from documind.core.chat import ChatManager
from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager
from tests.fake_llm import FakeLLM


class FastEmbedder:
    model_id: str = "fast-embedder"
    dim: int = 384

    def embed_query(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        vec[0] = 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


@pytest.fixture
def chat_app(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="a" * 32,
        min_score=0.35,
        allow_debug=True,
    )
    dm = DocuMind(
        settings=settings,
        store=NumpyStore(),
        embedder=FastEmbedder(),
        llm=FakeLLM(reply="DocuMind grounded response. [S1]"),
    )
    app = create_app(dm=dm, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=FastEmbedder(),
        shared_llm=FakeLLM(reply="DocuMind grounded response. [S1]"),
        settings=settings,
        ttl_seconds=3600,
    )
    app.state.chat_manager = ChatManager(db_path=tmp_path / "chat.db")
    return app


def test_static_404_html_and_json_negotiation(chat_app):
    client = TestClient(chat_app)

    # 1. Browser request with text/html gets polished static 404 HTML
    html_resp = client.get(
        "/nonexistent-page",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert html_resp.status_code == 404
    assert "text/html" in html_resp.headers["content-type"]
    assert "404: Not Found" in html_resp.text
    assert "This page does not exist" in html_resp.text
    assert "Go back home" in html_resp.text
    # Verify no server trace or python leak
    assert "Traceback" not in html_resp.text
    assert "documind" not in html_resp.text.lower() or "DocuMind" in html_resp.text

    # 2. API client requesting JSON gets standard API error envelope
    json_resp = client.get("/nonexistent-endpoint", headers={"Accept": "application/json"})
    assert json_resp.status_code == 404
    assert "application/json" in json_resp.headers["content-type"]
    data = json_resp.json()
    assert "error" in data
    assert data["error"]["code"] == "not_found"


def test_chatbot_ui_mounting(chat_app):
    client = TestClient(chat_app)

    # 1. Chatbot UI page loads with HTTP 200
    chat_resp = client.get("/app/chat.html")
    assert chat_resp.status_code == 200
    assert "DocuMind" in chat_resp.text
    assert "api.js" in chat_resp.text
    assert "chat-input" in chat_resp.text
    assert "message-stream" in chat_resp.text
    assert "citation-drawer" in chat_resp.text
    assert "btn-attach" in chat_resp.text

    # 2. Static 404 page is also accessible directly
    static_404_resp = client.get("/app/404.html")
    assert static_404_resp.status_code == 200
    assert "404: Not Found" in static_404_resp.text
    assert "Go back home" in static_404_resp.text


def test_conversation_deletion_and_isolation(chat_app):
    client = TestClient(chat_app)

    # 1. Create session A
    resp_sess_a = client.post("/api/demo/session")
    assert resp_sess_a.status_code == 201
    sid_a = resp_sess_a.json()["session_id"]
    headers_a = {"X-Session-ID": sid_a}

    # 2. Create session B
    resp_sess_b = client.post("/api/demo/session")
    assert resp_sess_b.status_code == 201
    sid_b = resp_sess_b.json()["session_id"]
    headers_b = {"X-Session-ID": sid_b}

    # 3. Create conversation in session A directly via chat_manager
    chat_mgr = chat_app.state.chat_manager
    session_hash_a = chat_app.state.session_manager.validate_token(sid_a)
    conv_id = chat_mgr.create_conversation(session_hash_a, title="Test Thread")
    assert conv_id is not None

    # 4. Session B attempts to delete Session A's conversation -> 404 (Isolation check)
    del_b = client.delete(f"/api/demo/conversations/{conv_id}", headers=headers_b)
    assert del_b.status_code == 404

    # 5. Session A deletes its own conversation -> 200 OK
    del_a = client.delete(f"/api/demo/conversations/{conv_id}", headers=headers_a)
    assert del_a.status_code == 200
    assert del_a.json()["status"] == "deleted"

    # 6. Verify conversation is removed
    assert chat_mgr.get_conversation(conv_id) is None


def test_document_listing_returns_chunks_and_chunk_count(chat_app):
    client = TestClient(chat_app)
    resp_sess = client.post("/api/demo/session")
    sid = resp_sess.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Upload sample text document
    file_content = b"Kernel process scheduling manages threads and priority queues."
    files = {"file": ("kernel_sched.txt", file_content, "text/plain")}
    up_resp = client.post("/api/demo/documents", headers=headers, files=files)
    assert up_resp.status_code == 201
    up_data = up_resp.json()
    assert "chunks" in up_data
    assert "chunk_count" in up_data
    assert up_data["chunks"] > 0
    assert up_data["chunk_count"] == up_data["chunks"]

    # List documents
    list_resp = client.get("/api/demo/documents", headers=headers)
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) == 1
    assert "chunks" in docs[0]
    assert "chunk_count" in docs[0]
    assert docs[0]["chunks"] == up_data["chunks"]
    assert docs[0]["chunk_count"] == docs[0]["chunks"]


def test_unconfigured_llm_emits_guidance_and_unconfigured_outcome(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="a" * 32,
        min_score=0.35,
        llm_provider="none",
    )
    dm = DocuMind(
        settings=settings,
        store=NumpyStore(),
        embedder=FastEmbedder(),
        llm=None,  # No LLM configured
    )
    app = create_app(dm=dm, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=FastEmbedder(),
        shared_llm=None,
        settings=settings,
        ttl_seconds=3600,
    )
    app.state.chat_manager = ChatManager(db_path=tmp_path / "chat.db")

    client = TestClient(app)
    resp_sess = client.post("/api/demo/session")
    sid = resp_sess.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # Upload document
    files = {"file": ("doc.txt", b"Photosynthesis transforms light into energy.", "text/plain")}
    client.post("/api/demo/documents", headers=headers, files=files)

    # Ask question
    chat_resp = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "What is photosynthesis?"},
    )
    assert chat_resp.status_code == 200
    lines = chat_resp.text.split("\n")
    events = [line for line in lines if line.startswith("event: ")]
    assert "event: token" in events
    assert "event: citations" in events
    assert "event: done" in events
    assert "No language model configured" in chat_resp.text
    assert '"outcome": "unconfigured_model"' in chat_resp.text

