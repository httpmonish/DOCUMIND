"""tests/test_demo_isolation.py
Tests for public demo gateway, session-aware document operations,
and multi-user physical & logical document isolation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager


@pytest.fixture
def isolated_app():
    temp_dir = Path(tempfile.mkdtemp())
    settings = Settings(
        home=temp_dir,
        api_key="test_key_minimum_32_characters_long_for_security_checks",
        env="dev",
        min_score=0.35,
    )

    # Fast in-memory dummy embedder
    class FastEmbedder:
        model_id = "test-model"
        dim = 4

        def embed_query(self, text: str):
            import numpy as np

            v = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
            return v

        def embed_documents(self, texts):
            import numpy as np

            arr = np.zeros((len(texts), 4), dtype=np.float32)
            for i in range(len(texts)):
                arr[i, 0] = 1.0
            return arr

    dummy_embedder = FastEmbedder()
    store = NumpyStore(dim=4)
    engine = DocuMind(settings=settings, embedder=dummy_embedder, store=store, llm=None)

    session_mgr = SessionManager(
        base_dir=temp_dir / "sessions",
        shared_embedder=dummy_embedder,
        shared_llm=None,
        settings=settings,
    )

    app = create_app(dm=engine, settings=settings)
    app.state.session_manager = session_mgr
    return app


def test_session_id_validation_required(isolated_app):
    client = TestClient(isolated_app)

    # 1. Missing session header
    resp = client.get("/api/demo/documents")
    assert resp.status_code == 400
    assert "Missing required X-Session-ID" in resp.json()["error"]["message"]

    # 2. Invalid session header (too short)
    resp = client.get("/api/demo/documents", headers={"X-Session-ID": "short"})
    assert resp.status_code == 400
    assert "Invalid session ID" in resp.json()["error"]["message"]

    # 3. Path traversal attempt in session ID
    resp = client.get("/api/demo/documents", headers={"X-Session-ID": "../../etc_passwd_123456"})
    assert resp.status_code == 400
    assert "Invalid session ID" in resp.json()["error"]["message"]


def test_multi_user_document_isolation(isolated_app):
    client = TestClient(isolated_app)

    session_a = "session_user_alice_1234567890abcdef"
    session_b = "session_user_bob_1234567890abcdef"

    headers_a = {"X-Session-ID": session_a}
    headers_b = {"X-Session-ID": session_b}

    # Initially both sessions have empty document lists
    resp_a = client.get("/api/demo/documents", headers=headers_a)
    resp_b = client.get("/api/demo/documents", headers=headers_b)
    assert resp_a.status_code == 200 and resp_a.json() == []
    assert resp_b.status_code == 200 and resp_b.json() == []

    # Alice uploads a document
    alice_content = b"Kernel scheduling manages execution queue threads deterministically."
    resp_upload_a = client.post(
        "/api/demo/documents",
        headers=headers_a,
        files={"file": ("alice_notes.txt", alice_content, "text/plain")},
    )
    assert resp_upload_a.status_code == 201
    assert resp_upload_a.json()["source"] == "alice_notes.txt"

    # Alice now sees her document
    resp_a = client.get("/api/demo/documents", headers=headers_a)
    assert resp_a.status_code == 200
    docs_a = resp_a.json()
    assert len(docs_a) == 1
    assert docs_a[0]["source"] == "alice_notes.txt"

    # Bob STILL sees empty list (isolation check 1)
    resp_b = client.get("/api/demo/documents", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json() == []

    # Bob attempts to inspect chunks of Alice's document -> 404 (isolation check 2)
    resp_chunks_b = client.get("/api/demo/documents/alice_notes.txt/chunks", headers=headers_b)
    assert resp_chunks_b.status_code == 404

    # Alice CAN inspect her chunks
    resp_chunks_a = client.get("/api/demo/documents/alice_notes.txt/chunks", headers=headers_a)
    assert resp_chunks_a.status_code == 200
    assert len(resp_chunks_a.json()) > 0

    # Bob attempts to delete Alice's document -> 404 (isolation check 3)
    resp_del_b = client.delete("/api/demo/documents/alice_notes.txt", headers=headers_b)
    assert resp_del_b.status_code == 404

    # Bob asks a question -> index empty error (cross-session vector query blocked)
    resp_ask_b = client.post(
        "/api/demo/ask",
        headers=headers_b,
        json={"question": "What is kernel scheduling?"},
    )
    assert resp_ask_b.status_code == 409
    assert resp_ask_b.json()["error"]["code"] == "index_empty"

    # Alice asks a question -> succeeds and retrieves her document
    resp_ask_a = client.post(
        "/api/demo/ask",
        headers=headers_a,
        json={"question": "What is kernel scheduling?"},
    )
    assert resp_ask_a.status_code == 200
    ans_data = resp_ask_a.json()
    assert "citations" in ans_data
    assert len(ans_data["citations"]) > 0
    assert ans_data["citations"][0]["source"] == "alice_notes.txt"

    # Bob uploads his own document with the EXACT same filename
    bob_content = b"Database indexing uses B-Trees and LSM Trees for fast disk retrieval."
    resp_upload_b = client.post(
        "/api/demo/documents",
        headers=headers_b,
        files={"file": ("alice_notes.txt", bob_content, "text/plain")},
    )
    assert resp_upload_b.status_code == 201

    # Bob's chunks are database indexing, Alice's chunks are kernel scheduling
    url = "/api/demo/documents/alice_notes.txt/chunks"
    chunks_bob = client.get(url, headers=headers_b).json()
    chunks_alice = client.get(url, headers=headers_a).json()

    assert "Database indexing" in chunks_bob[0]["text"]
    assert "Kernel scheduling" in chunks_alice[0]["text"]

    # Alice deletes her document -> Bob's document remains unaffected
    resp_del_a = client.delete("/api/demo/documents/alice_notes.txt", headers=headers_a)
    assert resp_del_a.status_code == 204

    # Alice's document is gone
    assert client.get("/api/demo/documents", headers=headers_a).json() == []

    # Bob's document is still there!
    assert len(client.get("/api/demo/documents", headers=headers_b).json()) == 1


def test_no_secret_leakage_in_demo_responses(isolated_app):
    client = TestClient(isolated_app)
    headers = {"X-Session-ID": "session_security_check_1234567890"}

    # Upload document
    client.post(
        "/api/demo/documents",
        headers=headers,
        files={"file": ("doc.txt", b"Safety checks and validation details.", "text/plain")},
    )

    resp_meta = client.get("/api/demo/meta", headers=headers)
    assert resp_meta.status_code == 200
    meta_text = str(resp_meta.json())
    assert "test_key_minimum_32" not in meta_text
    assert "sk-ant" not in meta_text

    resp_ask = client.post(
        "/api/demo/ask",
        headers=headers,
        json={"question": "What are safety checks?"},
    )
    assert resp_ask.status_code == 200
    ask_text = str(resp_ask.json())
    assert "test_key_minimum_32" not in ask_text
    assert "sk-ant" not in ask_text


def test_demo_analyze_and_file_validation(isolated_app):
    client = TestClient(isolated_app)
    headers = {"X-Session-ID": "session_analyze_test_1234567890"}

    # Unsupported extension (.exe)
    resp_exe = client.post(
        "/api/demo/documents",
        headers=headers,
        files={"file": ("malware.exe", b"binary content", "application/octet-stream")},
    )
    assert resp_exe.status_code == 415

    # Upload valid markdown
    md_content = b"# Operating Systems\nProcesses are allocated memory in user space."
    resp_upload = client.post(
        "/api/demo/documents",
        headers=headers,
        files={"file": ("os_notes.md", md_content, "text/markdown")},
    )
    assert resp_upload.status_code == 201

    # Duplicate without replace -> 409 Conflict
    resp_dup = client.post(
        "/api/demo/documents",
        headers=headers,
        files={"file": ("os_notes.md", b"# Modified content\nChanged text.", "text/markdown")},
    )
    assert resp_dup.status_code == 409

    # Replace with replace=true -> 201
    resp_replace = client.post(
        "/api/demo/documents?replace=true",
        headers=headers,
        files={"file": ("os_notes.md", b"# Modified content\nChanged text.", "text/markdown")},
    )
    assert resp_replace.status_code == 201

    # Analysis: summarize
    resp_summary = client.post(
        "/api/demo/analyze",
        headers=headers,
        json={"action": "summarize", "source": "os_notes.md"},
    )
    assert resp_summary.status_code == 200

    # Analysis: key_points
    resp_kp = client.post(
        "/api/demo/analyze",
        headers=headers,
        json={"action": "key_points"},
    )
    assert resp_kp.status_code == 200

    # Analysis: invalid action -> 422
    resp_inv = client.post(
        "/api/demo/analyze",
        headers=headers,
        json={"action": "hack_system"},
    )
    assert resp_inv.status_code == 422


def test_session_cleanup_lifecycle(isolated_app):
    session_mgr: SessionManager = isolated_app.state.session_manager
    session_id = "session_cleanup_test_1234567890"

    engine, _ = session_mgr.get_engine(session_id)
    session_dir = session_mgr.get_session_dir(session_id)
    assert session_dir.exists()

    # Manual delete
    deleted = session_mgr.delete_session(session_id)
    assert deleted is True
    assert not session_dir.exists()

