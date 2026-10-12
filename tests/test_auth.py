"""Unit tests for Phase 5 user authentication, scrypt hashing, and tenant workspace isolation."""

import io
from pathlib import Path

from starlette.testclient import TestClient

from documind.core.config import Settings
from documind.interfaces.api import create_app


def test_auth_registration_validation(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="12345678901234567890123456789012",
        env="dev",
        embed_model="BAAI/bge-small-en-v1.5",
        llm_provider="none",
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    # Password too short (<10 chars)
    resp = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "short"},
    )
    assert resp.status_code == 400
    err_body = resp.json().get("error", resp.json())
    msg = err_body.get("message", err_body.get("detail", ""))
    assert "at least 10 characters" in msg

    # Invalid email
    resp = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "securepassword123"},
    )
    assert resp.status_code == 400
    err_body = resp.json().get("error", resp.json())
    msg = err_body.get("message", err_body.get("detail", ""))
    assert "Invalid email" in msg


def test_auth_register_login_logout_flow(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="12345678901234567890123456789012",
        env="dev",
        embed_model="BAAI/bge-small-en-v1.5",
        llm_provider="none",
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    # Initial check /api/auth/me -> not authenticated
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is False

    # 1. Register Alice
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": "Alice@Example.com", "password": "Password1234!"},
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert reg_data["status"] == "ok"
    assert reg_data["user"]["email"] == "alice@example.com"
    assert "documind_auth_session" in client.cookies

    # Duplicate register -> 400 generic error
    dup_resp = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "AnotherPassword999!"},
    )
    assert dup_resp.status_code == 400

    # 2. Check /api/auth/me with cookie
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is True
    assert me_resp.json()["user"]["email"] == "alice@example.com"

    # 3. Logout
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200

    # /api/auth/me is now unauthenticated
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is False

    # 4. Failed login
    bad_login = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401
    err_body = bad_login.json().get("error", bad_login.json())
    msg = err_body.get("message", err_body.get("detail", ""))
    assert "Invalid email or password" in msg

    # 5. Successful login
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "Password1234!"},
    )
    assert login_resp.status_code == 200
    assert "documind_auth_session" in client.cookies


def test_tenant_workspace_isolation(tmp_path: Path):
    """User A and User B workspaces are strictly isolated. User B can never read User A's chunks."""
    settings = Settings(
        home=tmp_path,
        api_key="12345678901234567890123456789012",
        env="dev",
        embed_model="BAAI/bge-small-en-v1.5",
        llm_provider="none",
    )
    app = create_app(settings=settings)
    client_a = TestClient(app)
    client_b = TestClient(app)

    # 1. Register User A
    resp_a = client_a.post(
        "/api/auth/register",
        json={"email": "user_a@example.com", "password": "PasswordUserA123!"},
    )
    assert resp_a.status_code == 201

    # 2. User A uploads a secret document
    file_content = b"Top secret classified notes of User A. Quantum algorithms for teleportation."
    upload_resp = client_a.post(
        "/api/demo/documents",
        files={"file": ("secret_user_a.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert upload_resp.status_code == 201
    assert upload_resp.json()["status"] == "indexed"

    # Verify User A sees the document
    docs_a = client_a.get("/api/demo/documents").json()
    doc_list_a = docs_a if isinstance(docs_a, list) else docs_a.get("documents", [])
    assert len(doc_list_a) == 1
    assert doc_list_a[0]["source"] == "secret_user_a.txt"

    # User A can get chunks
    chunks_a = client_a.get("/api/demo/documents/secret_user_a.txt/chunks")
    assert chunks_a.status_code == 200
    chunks_data = chunks_a.json()
    chunks_list = chunks_data if isinstance(chunks_data, list) else chunks_data.get("chunks", [])
    assert len(chunks_list) >= 1

    # 3. Register User B in separate client session
    resp_b = client_b.post(
        "/api/auth/register",
        json={"email": "user_b@example.com", "password": "PasswordUserB456!"},
    )
    assert resp_b.status_code == 201

    # User B should see 0 documents
    docs_b = client_b.get("/api/demo/documents").json()
    doc_list_b = docs_b if isinstance(docs_b, list) else docs_b.get("documents", [])
    assert len(doc_list_b) == 0

    # User B attempting to access User A's chunks returns 404
    chunks_b = client_b.get("/api/demo/documents/secret_user_a.txt/chunks")
    assert chunks_b.status_code == 404
    err_body = chunks_b.json().get("error", chunks_b.json())
    assert (
        err_body.get("code") in {"DOCUMENT_NOT_FOUND", "NOT_FOUND"}
        or "not found" in str(err_body).lower()
    )

    # User B attempting to delete User A's document returns 404
    del_b = client_b.delete("/api/demo/documents/secret_user_a.txt")
    assert del_b.status_code == 404


def test_claim_guest_session_on_register(tmp_path: Path):
    """Guest session documents can be claimed and migrated to user workspace."""
    settings = Settings(
        home=tmp_path,
        api_key="12345678901234567890123456789012",
        env="dev",
        embed_model="BAAI/bge-small-en-v1.5",
        llm_provider="none",
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    # 1. Start guest session
    guest_init = client.post("/api/demo/session")
    assert guest_init.status_code == 201
    guest_sid = guest_init.json()["session_id"]

    # 2. Upload file in guest session
    file_bytes = b"DocuMind guest document indexed before account registration."
    up = client.post(
        "/api/demo/documents",
        headers={"X-Session-ID": guest_sid},
        files={"file": ("guest_memo.txt", io.BytesIO(file_bytes), "text/plain")},
    )
    assert up.status_code == 201

    # 3. Register with claim_guest_session
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "converted_guest@example.com",
            "password": "SecurePassword123!",
            "claim_guest_session": guest_sid,
        },
    )
    assert reg.status_code == 201

    # 4. Authenticated user sees the migrated document in their persistent account!
    docs = client.get("/api/demo/documents").json()
    doc_list = docs if isinstance(docs, list) else docs.get("documents", [])
    sources = [d["source"] for d in doc_list]
    assert "guest_memo.txt" in sources
