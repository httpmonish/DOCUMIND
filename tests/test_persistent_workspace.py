"""tests/test_persistent_workspace.py
Automated end-to-end tests for DocuMind persistent relational database,
user workspace, recent documents, chat history restoration, and tenant isolation.
"""

from __future__ import annotations

import io
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Usage
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.auth import AuthManager
from documind.interfaces.session import SessionManager


class FastTestEmbedder:
    model_id = "test-workspace-embedder"
    dim = 384

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


class FakeTestLLM:
    model_id = "test-workspace-llm"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            "Verified answer from document analysis. [S1]",
            Usage(input_tokens=80, output_tokens=25),
        )


def build_workspace_app(
    tmp_path: Path,
    db_filename: str = "workspace_auth.db",
) -> tuple[Any, AuthManager]:
    settings = Settings(
        home=tmp_path,
        api_key="c" * 32,
        require_auth=True,
        allow_debug=True,
    )
    embedder = FastTestEmbedder()
    store = NumpyStore(dim=384)
    llm = FakeTestLLM()
    dm = DocuMind(settings=settings, embedder=embedder, store=store, llm=llm)

    app = create_app(dm=dm, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=embedder,
        shared_llm=llm,
        settings=settings,
        ttl_seconds=3600,
    )
    auth_mgr = AuthManager(
        db_path=tmp_path / db_filename,
        database_url=settings.database_url,
    )
    app.state.auth_manager = auth_mgr
    return app, auth_mgr


def test_user_registration_profile_persistence(tmp_path: Path) -> None:
    """Validate user registration, password hashing security, profile loading and updating."""
    app, auth_mgr = build_workspace_app(tmp_path)
    client = TestClient(app)

    # 1. Register new user
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "SecurePassword123!",
            "display_name": "Alice Liddell",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["status"] == "ok"
    assert reg_data["user"]["email"] == "alice@example.com"
    assert reg_data["user"]["display_name"] == "Alice Liddell"
    assert "token" in reg_data

    # 2. Duplicate registration rejected
    dup_resp = client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "AnotherPassword456!",
        },
    )
    assert dup_resp.status_code in {400, 409}

    # 3. Verify passwords NOT stored in plaintext in SQLite
    with sqlite3.connect(auth_mgr.db_path) as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT password_hash, salt FROM users WHERE email = 'alice@example.com'"
        row = conn.execute(query).fetchone()
        assert row is not None
        assert row["password_hash"] != b""
        assert b"SecurePassword123!" not in row["password_hash"]
        assert len(row["salt"]) in {16, 32}

    # 4. Login with registered user and load profile
    client.cookies.clear()
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "SecurePassword123!"},
    )
    assert login_resp.status_code == 200

    profile_resp = client.get("/api/auth/profile")
    assert profile_resp.status_code == 200
    profile_data = profile_resp.json()
    assert profile_data["email"] == "alice@example.com"
    assert profile_data["display_name"] == "Alice Liddell"
    assert profile_data["created_at"] > 0
    assert profile_data["last_login_at"] is not None

    # 5. Update user profile
    patch_resp = client.patch(
        "/api/auth/profile",
        json={"display_name": "Alice In Wonderland", "avatar_url": "https://example.com/avatar.png"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["display_name"] == "Alice In Wonderland"
    assert patch_resp.json()["avatar_url"] == "https://example.com/avatar.png"


def test_document_persistence_recent_and_isolation(tmp_path: Path) -> None:
    """Validate document metadata persistence, recent document sorting, and cross-user isolation."""
    db_file = "shared_workspace.db"
    app, _ = build_workspace_app(tmp_path, db_filename=db_file)
    client_a = TestClient(app)

    # Register User A
    client_a.post(
        "/api/auth/register",
        json={"email": "user_a@example.com", "password": "PasswordUserA123!"},
    )

    # Upload Doc 1
    doc1_content = b"DocuMind provides verifiable RAG retrieval architecture."
    up1 = client_a.post(
        "/api/demo/documents",
        files={"file": ("architecture.txt", io.BytesIO(doc1_content), "text/plain")},
    )
    assert up1.status_code == 201
    assert up1.json()["status"] == "indexed"

    time.sleep(0.05)

    # Upload Doc 2
    doc2_content = b"Financial quarterly earnings summary report."
    up2 = client_a.post(
        "/api/demo/documents",
        files={"file": ("earnings_q2.txt", io.BytesIO(doc2_content), "text/plain")},
    )
    assert up2.status_code == 201

    # List documents
    docs_resp = client_a.get("/api/demo/documents")
    assert docs_resp.status_code == 200
    docs = docs_resp.json()
    assert len(docs) >= 2
    sources = [d["source"] for d in docs]
    assert "architecture.txt" in sources
    assert "earnings_q2.txt" in sources

    # Check recent documents: earnings_q2.txt was uploaded last, should be first
    recent_resp = client_a.get("/api/demo/documents/recent?limit=5")
    assert recent_resp.status_code == 200
    recent_docs = recent_resp.json()
    assert len(recent_docs) >= 2
    assert recent_docs[0]["source"] == "earnings_q2.txt"

    # Now touch/access architecture.txt -> moves to top of recent documents
    touch_resp = client_a.get("/api/demo/documents/architecture.txt")
    assert touch_resp.status_code == 200
    assert touch_resp.json()["source"] == "architecture.txt"

    recent_resp2 = client_a.get("/api/demo/documents/recent?limit=5")
    recent_docs2 = recent_resp2.json()
    assert recent_docs2[0]["source"] == "architecture.txt"

    # Rename document
    rename_resp = client_a.patch(
        "/api/demo/documents/architecture.txt/rename",
        json={"display_name": "System Architecture v2"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["display_name"] == "System Architecture v2"

    # User B Cross-tenant isolation verification
    client_b = TestClient(app)
    client_b.post(
        "/api/auth/register",
        json={"email": "user_b@example.com", "password": "PasswordUserB456!"},
    )

    # User B cannot see User A's documents
    b_docs = client_b.get("/api/demo/documents").json()
    assert len(b_docs) == 0

    # User B cannot access User A's document chunks
    b_chunk_err = client_b.get("/api/demo/documents/architecture.txt/chunks")
    assert b_chunk_err.status_code in {403, 404}

    # User B cannot rename User A's document
    b_rename_err = client_b.patch(
        "/api/demo/documents/architecture.txt/rename",
        json={"display_name": "Hacked Name"},
    )
    assert b_rename_err.status_code in {403, 404}

    # User B cannot delete User A's document
    b_del_err = client_b.delete("/api/demo/documents/architecture.txt")
    assert b_del_err.status_code in {403, 404}

    # User A deletes architecture.txt
    del_resp = client_a.delete("/api/demo/documents/architecture.txt")
    assert del_resp.status_code == 204

    # Now architecture.txt is soft-deleted and removed from active documents
    a_docs_after = client_a.get("/api/demo/documents").json()
    assert not any(d["source"] == "architecture.txt" for d in a_docs_after)


def test_conversation_persistence_and_restoration(tmp_path: Path) -> None:
    """Validate conversation creation, message persistence, citations, and restoration."""
    db_file = "chat_workspace.db"
    app, auth_mgr = build_workspace_app(tmp_path, db_filename=db_file)
    client = TestClient(app)

    # 1. Register User
    client.post(
        "/api/auth/register",
        json={"email": "chat_user@example.com", "password": "ChatPassword123!"},
    )

    # Upload document to question
    doc_payload = io.BytesIO(b"DocuMind policy handbook details.")
    client.post(
        "/api/demo/documents",
        files={"file": ("handbook.txt", doc_payload, "text/plain")},
    )

    # 2. Ask first question via chat API
    chat_resp1 = client.post(
        "/api/demo/chat",
        json={"question": "What is the policy regarding RAG?"},
    )
    assert chat_resp1.status_code == 200
    chat_data1 = chat_resp1.json()
    conv_id = chat_data1["conversation_id"]
    assert conv_id is not None
    assert "Verified answer" in chat_data1["answer"]

    # 3. Ask follow-up in the same conversation thread
    chat_resp2 = client.post(
        "/api/demo/chat",
        json={
            "question": "Can you elaborate on verification?",
            "conversation_id": conv_id,
        },
    )
    assert chat_resp2.status_code == 200
    assert chat_resp2.json()["conversation_id"] == conv_id

    # 4. Verify message count and turns in DB
    conv_msgs_resp = client.get(f"/api/demo/conversations/{conv_id}/messages")
    assert conv_msgs_resp.status_code == 200
    msgs = conv_msgs_resp.json()
    assert len(msgs) == 4  # 2 user questions + 2 assistant responses
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What is the policy regarding RAG?"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    assert msgs[3]["role"] == "assistant"

    # Verify citations survived
    assert len(msgs[1]["citations"]) > 0

    # 5. Simulate browser close / logout and login on a new session
    client.post("/api/auth/logout")
    client.cookies.clear()

    # Re-login with same user
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "chat_user@example.com", "password": "ChatPassword123!"},
    )
    assert login_resp.status_code == 200

    # List conversations: previous thread is restored!
    convs_resp = client.get("/api/demo/conversations")
    assert convs_resp.status_code == 200
    conv_list = convs_resp.json()
    assert len(conv_list) >= 1
    assert any(c["id"] == conv_id for c in conv_list)

    # Restore messages
    restored_msgs = client.get(f"/api/demo/conversations/{conv_id}/messages").json()
    assert len(restored_msgs) == 4
    assert restored_msgs[0]["content"] == "What is the policy regarding RAG?"

    # 6. Rename conversation
    rename_resp = client.patch(
        f"/api/demo/conversations/{conv_id}",
        json={"title": "RAG Policy Review Thread"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["title"] == "RAG Policy Review Thread"

    # 7. User isolation check: Another user cannot read or delete this conversation
    client_intruder = TestClient(app)
    client_intruder.post(
        "/api/auth/register",
        json={"email": "intruder@example.com", "password": "IntruderPassword123!"},
    )
    intruder_resp = client_intruder.get(f"/api/demo/conversations/{conv_id}/messages")
    assert intruder_resp.status_code == 404

    intruder_del = client_intruder.delete(f"/api/demo/conversations/{conv_id}")
    assert intruder_del.status_code == 404

    # Delete conversation by legitimate owner
    del_conv_resp = client.delete(f"/api/demo/conversations/{conv_id}")
    assert del_conv_resp.status_code == 200
    assert client.get(f"/api/demo/conversations/{conv_id}/messages").status_code == 404
