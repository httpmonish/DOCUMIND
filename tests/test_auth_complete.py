"""tests/test_auth_complete.py
Comprehensive test suite verifying DOCUMIND authentication, Google OAuth 2.0 / OpenID Connect,
password reset lifecycle, and tenant workspace isolation.
"""

from __future__ import annotations

import io
import urllib.parse
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
    model_id = "test-auth-embedder"
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
    model_id = "test-auth-llm"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            "Response from secure test LLM. [S1]",
            Usage(input_tokens=100, output_tokens=25),
        )


def build_test_app(
    tmp_path: Path,
    *,
    require_auth: bool = True,
    google_client_id: str = "",
    google_client_secret: str = "",
    allow_debug: bool = True,
) -> tuple[Any, AuthManager]:
    settings = Settings(
        home=tmp_path,
        api_key="b" * 32,
        require_auth=require_auth,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        google_redirect_uri="http://testserver/api/auth/google/callback",
        allow_debug=allow_debug,
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
        db_path=tmp_path / "auth.db",
        database_url=settings.database_url,
    )
    app.state.auth_manager = auth_mgr
    return app, auth_mgr


def test_registration_input_validation(tmp_path: Path) -> None:
    """Registration requires valid email and minimum 10-character password."""
    app, _ = build_test_app(tmp_path)
    client = TestClient(app)

    # Password too short
    r_short = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "short"},
    )
    assert r_short.status_code == 400
    assert "at least 10 characters" in r_short.text

    # Invalid email format
    r_bad_email = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "SecurePassword123!"},
    )
    assert r_bad_email.status_code == 400
    assert "Invalid email" in r_bad_email.text

    # Valid registration with display name
    r_ok = client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "SecurePassword123!",
            "display_name": "Alice Liddell",
        },
    )
    assert r_ok.status_code == 201
    data = r_ok.json()
    assert data["status"] == "ok"
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["display_name"] == "Alice Liddell"
    assert "documind_auth_session" in client.cookies


def test_duplicate_registration_rejection(tmp_path: Path) -> None:
    """Duplicate email registration is rejected with HTTP 400."""
    app, _ = build_test_app(tmp_path)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "SecurePassword123!"},
    )

    r_dup = client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "DifferentPassword999!"},
    )
    assert r_dup.status_code == 400
    assert "Unable to register" in r_dup.text or "already registered" in r_dup.text


def test_login_invalid_credentials_and_success(tmp_path: Path) -> None:
    """Login safely handles invalid credentials and sets secure session cookie on success."""
    app, _ = build_test_app(tmp_path)
    client = TestClient(app)

    # Register user
    client.post(
        "/api/auth/register",
        json={"email": "charlie@example.com", "password": "SecurePassword123!"},
    )

    # Clear cookies
    client.cookies.clear()

    # Wrong email
    r_wrong_email = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "SecurePassword123!"},
    )
    assert r_wrong_email.status_code == 401
    assert "Invalid email or password" in r_wrong_email.text

    # Wrong password
    r_wrong_pw = client.post(
        "/api/auth/login",
        json={"email": "charlie@example.com", "password": "IncorrectPassword!"},
    )
    assert r_wrong_pw.status_code == 401
    assert "Invalid email or password" in r_wrong_pw.text

    # Valid login
    r_ok = client.post(
        "/api/auth/login",
        json={"email": "charlie@example.com", "password": "SecurePassword123!"},
    )
    assert r_ok.status_code == 200
    assert "documind_auth_session" in client.cookies

    # Verify session via /api/auth/me
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["user"]["email"] == "charlie@example.com"


def test_logout_session_invalidation(tmp_path: Path) -> None:
    """Logging out revokes the session on both server and client."""
    app, _ = build_test_app(tmp_path)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "dave@example.com", "password": "SecurePassword123!"},
    )
    assert "documind_auth_session" in client.cookies
    token = client.cookies.get("documind_auth_session")

    # Logout
    r_out = client.post("/api/auth/logout")
    assert r_out.status_code == 200

    # Cookie is gone or empty
    me_after = client.get("/api/auth/me")
    assert me_after.json()["authenticated"] is False

    # Attempting to reuse revoked session token in header/cookie fails
    if token:
        client.cookies.set("documind_auth_session", token)
        me_reused = client.get("/api/auth/me")
        assert me_reused.json()["authenticated"] is False


def test_password_reset_lifecycle(tmp_path: Path) -> None:
    """Password reset request, single-use token confirm, and session revocation."""
    app, _ = build_test_app(tmp_path, allow_debug=True)
    client = TestClient(app)

    # 1. Non-existent email request returns 200 without leaking account absence
    r_missing = client.post(
        "/api/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )
    assert r_missing.status_code == 200
    assert "debug_token" not in r_missing.json()

    # 2. Register Eve
    client.post(
        "/api/auth/register",
        json={"email": "eve@example.com", "password": "OriginalPassword123!"},
    )

    # Eve has an active session
    active_token = client.cookies.get("documind_auth_session")

    # 3. Request reset for Eve
    r_req = client.post(
        "/api/auth/password-reset/request",
        json={"email": "eve@example.com"},
    )
    assert r_req.status_code == 200
    reset_token = r_req.json().get("debug_token")
    assert reset_token is not None

    # 4. Confirm with invalid token -> 400
    r_bad_token = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "invalid-token-123", "new_password": "NewSecurePassword123!"},
    )
    assert r_bad_token.status_code == 400

    # 5. Confirm with password too short -> 400
    r_short_pw = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "short"},
    )
    assert r_short_pw.status_code == 400

    # 6. Confirm with valid token & password -> 200
    r_confirm = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "NewSecurePassword123!"},
    )
    assert r_confirm.status_code == 200

    # 7. Token is single-use -> re-submitting fails
    r_reuse = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "new_password": "AnotherNewPassword123!"},
    )
    assert r_reuse.status_code == 400

    # 8. Eve's prior active session was revoked on password reset
    if active_token:
        client.cookies.set("documind_auth_session", active_token)
        me_resp = client.get("/api/auth/me")
        assert me_resp.json()["authenticated"] is False

    # 9. Eve logs in with new password
    r_new_login = client.post(
        "/api/auth/login",
        json={"email": "eve@example.com", "password": "NewSecurePassword123!"},
    )
    assert r_new_login.status_code == 200

    # Old password no longer works
    client.cookies.clear()
    r_old_login = client.post(
        "/api/auth/login",
        json={"email": "eve@example.com", "password": "OriginalPassword123!"},
    )
    assert r_old_login.status_code == 401


def test_google_oauth_authorize_endpoint(tmp_path: Path) -> None:
    """GET /api/auth/google/authorize handles unconfigured vs configured states."""
    # Unconfigured credentials -> 503
    app_unconfigured, _ = build_test_app(tmp_path / "app1")
    client_unconfigured = TestClient(app_unconfigured)

    r_503 = client_unconfigured.get("/api/auth/google/authorize")
    assert r_503.status_code == 503

    # Configured credentials -> 302 redirect with state cookie
    app_configured, _ = build_test_app(
        tmp_path / "app2",
        google_client_id="mock-client-id.apps.googleusercontent.com",
        google_client_secret="mock-client-secret",  # noqa: S106
    )
    client_configured = TestClient(app_configured)

    r_302 = client_configured.get(
        "/api/auth/google/authorize?redirect=/app/library/code.html",
        follow_redirects=False,
    )
    assert r_302.status_code == 302
    assert "accounts.google.com" in r_302.headers["location"]
    assert "mock-client-id" in r_302.headers["location"]
    assert "documind_oauth_state" in client_configured.cookies


def test_google_oauth_callback_flow(tmp_path: Path) -> None:
    """Google OAuth callback handles errors, state validation, registration,
    and email collision protection.
    """
    app, _ = build_test_app(
        tmp_path,
        google_client_id="mock-client-id",
        google_client_secret="mock-client-secret",  # noqa: S106
    )
    client = TestClient(app)

    # 1. Google returns error (e.g. user cancelled)
    client.cookies.set("documind_oauth_state", "nonce123:/app/console/code.html")
    r_err = client.get(
        "/api/auth/google/callback?error=access_denied",
        follow_redirects=False,
    )
    assert r_err.status_code == 302
    assert "error=access_denied" in r_err.headers["location"]

    # 2. State mismatch
    r_mismatch = client.get(
        "/api/auth/google/callback?state=wrong_nonce&code=mock_code",
        follow_redirects=False,
    )
    assert r_mismatch.status_code == 302
    assert "error=invalid_state" in r_mismatch.headers["location"]

    # 3. Successful Google login with mock exchange
    mock_google_profile = {
        "sub": "google-sub-987654321",
        "email": "google_user@gmail.com",
        "name": "Google User",
        "picture": "https://example.com/avatar.png",
        "email_verified": True,
    }
    app.state.mock_google_oauth = lambda code, redirect_uri: mock_google_profile

    # Initialize state cookie
    client.cookies.set("documind_oauth_state", "valid_nonce_1:/app/library/code.html")
    r_callback = client.get(
        "/api/auth/google/callback?state=valid_nonce_1&code=mock_auth_code",
        follow_redirects=False,
    )
    assert r_callback.status_code == 302
    assert r_callback.headers["location"] == "/app/library/code.html"
    assert "documind_auth_session" in client.cookies

    # Verify session is valid and user is authenticated
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["user"]["email"] == "google_user@gmail.com"
    assert me_data["user"]["display_name"] == "Google User"

    # 4. Returning Google login with same sub works seamlessly
    client.cookies.clear()
    client.cookies.set("documind_oauth_state", "valid_nonce_2:/app/console/code.html")
    r_returning = client.get(
        "/api/auth/google/callback?state=valid_nonce_2&code=mock_auth_code",
        follow_redirects=False,
    )
    assert r_returning.status_code == 302
    assert "documind_auth_session" in client.cookies

    # 5. Account collision protection:
    # A user already registered with password 'frank@example.com' without Google linked
    client_frank = TestClient(app)
    client_frank.post(
        "/api/auth/register",
        json={"email": "frank@example.com", "password": "PasswordFrank123!"},
    )
    client_frank.cookies.clear()

    # An attacker/external Google profile claims to have 'frank@example.com' with different sub
    app.state.mock_google_oauth = lambda code, redirect_uri: {
        "sub": "unlinked-google-sub-555",
        "email": "frank@example.com",
        "name": "Frank Impersonator",
        "email_verified": True,
    }
    client_frank.cookies.set("documind_oauth_state", "valid_nonce_3:/app/console/code.html")
    r_collision = client_frank.get(
        "/api/auth/google/callback?state=valid_nonce_3&code=mock_code",
        follow_redirects=False,
    )
    assert r_collision.status_code == 302
    loc = r_collision.headers["location"]
    assert "error=account_exists_link_required" in loc
    assert urllib.parse.quote("frank@example.com") in loc


def test_anonymous_upload_rejection_when_unauthenticated(tmp_path: Path) -> None:
    """Anonymous requests to document endpoints receive HTTP 401 Unauthorized."""
    app, _ = build_test_app(tmp_path, require_auth=True)
    anon_client = TestClient(app)

    # 1. Anonymous upload -> 401
    pdf_bytes = b"%PDF-1.4 Mock confidential test document."
    r_up = anon_client.post(
        "/api/demo/documents",
        files={"file": ("classified.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert r_up.status_code == 401
    assert "Authentication required" in r_up.text

    # 2. Anonymous list documents -> 401
    r_list = anon_client.get("/api/demo/documents")
    assert r_list.status_code == 401

    # 3. Anonymous inspect chunks -> 401
    r_chunks = anon_client.get("/api/demo/documents/classified.pdf/chunks")
    assert r_chunks.status_code == 401

    # 4. Anonymous delete document -> 401
    r_del = anon_client.delete("/api/demo/documents/classified.pdf")
    assert r_del.status_code == 401

    # 5. Anonymous chat -> 401
    r_chat = anon_client.post(
        "/api/demo/chat",
        json={"question": "What is in the document?"},
    )
    assert r_chat.status_code == 401


def test_tenant_workspace_isolation_comprehensive(tmp_path: Path) -> None:
    """Strict workspace isolation: User B cannot view, chunk, or delete User A's documents."""
    app, _ = build_test_app(tmp_path, require_auth=True)
    client_a = TestClient(app)
    client_b = TestClient(app)

    # 1. Register User A and upload doc_a.txt
    client_a.post(
        "/api/auth/register",
        json={"email": "usera@example.com", "password": "PasswordUserA123!"},
    )
    payload_a = io.BytesIO(b"Data owned exclusively by User A.")
    r_up_a = client_a.post(
        "/api/demo/documents",
        files={"file": ("doc_a.txt", payload_a, "text/plain")},
    )
    assert r_up_a.status_code == 201

    # 2. Register User B and upload doc_b.txt
    client_b.post(
        "/api/auth/register",
        json={"email": "userb@example.com", "password": "PasswordUserB456!"},
    )
    payload_b = io.BytesIO(b"Data owned exclusively by User B.")
    r_up_b = client_b.post(
        "/api/demo/documents",
        files={"file": ("doc_b.txt", payload_b, "text/plain")},
    )
    assert r_up_b.status_code == 201

    # 3. Verify User A only sees doc_a.txt
    docs_a = client_a.get("/api/demo/documents").json()
    list_a = docs_a if isinstance(docs_a, list) else docs_a.get("documents", [])
    sources_a = [d["source"] for d in list_a]
    assert "doc_a.txt" in sources_a
    assert "doc_b.txt" not in sources_a

    # 4. Verify User B only sees doc_b.txt
    docs_b = client_b.get("/api/demo/documents").json()
    list_b = docs_b if isinstance(docs_b, list) else docs_b.get("documents", [])
    sources_b = [d["source"] for d in list_b]
    assert "doc_b.txt" in sources_b
    assert "doc_a.txt" not in sources_b

    # 5. User A querying User B's chunks -> 404
    r_a_on_b = client_a.get("/api/demo/documents/doc_b.txt/chunks")
    assert r_a_on_b.status_code == 404

    # 6. User B querying User A's chunks -> 404
    r_b_on_a = client_b.get("/api/demo/documents/doc_a.txt/chunks")
    assert r_b_on_a.status_code == 404

    # 7. User A deleting User B's document -> 404
    del_a_on_b = client_a.delete("/api/demo/documents/doc_b.txt")
    assert del_a_on_b.status_code == 404

    # 8. User B deleting User A's document -> 404
    del_b_on_a = client_b.delete("/api/demo/documents/doc_a.txt")
    assert del_b_on_a.status_code == 404

    # 9. User A can delete their own document
    del_a = client_a.delete("/api/demo/documents/doc_a.txt")
    assert del_a.status_code in (200, 204)

    docs_a_after = client_a.get("/api/demo/documents").json()
    list_a_after = (
        docs_a_after if isinstance(docs_a_after, list) else docs_a_after.get("documents", [])
    )
    sources_a_after = [d["source"] for d in list_a_after]
    assert "doc_a.txt" not in sources_a_after
