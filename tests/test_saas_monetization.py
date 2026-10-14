"""tests/test_saas_monetization.py
Comprehensive automated regression and acceptance test suite for DocuMind SaaS Monetization,
Lifetime Free-Tier Limits, Concurrency-Safe Quota Enforcement, and Razorpay Subscriptions.
"""

from __future__ import annotations

import concurrent.futures
import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient

from documind.core.billing import RazorpayManager
from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Usage
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.auth import AuthManager
from documind.interfaces.session import SessionManager


class MockDeterministicLLM:
    """Mock LLM that tracks call count to verify LLM is never invoked once quota is exhausted."""

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        self.call_count += 1
        return (
            "Grounded answer citing source [S1].",
            Usage(input_tokens=100, output_tokens=30),
        )


class FastAlignedEmbedder:
    model_id = "test-saas-embedder"
    dim = 64

    def embed_query(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        if "irrelevant" in text.lower():
            vec[1] = 1.0  # orthogonal to documents
        else:
            vec[0] = 1.0
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


def build_saas_app(
    tmp_path: Path,
    free_doc_limit: int = 1,
    free_question_limit: int = 5,
    key_id: str = "rzp_test_mock_key_id",
    key_secret: str = "mock_secret_key_32_chars_long_123",  # noqa: S107
    webhook_secret: str = "mock_webhook_secret_key_123",  # noqa: S107
) -> tuple[Any, AuthManager, MockDeterministicLLM]:
    settings = Settings(
        home=tmp_path,
        api_key="a" * 32,
        require_auth=True,
        allow_debug=True,
        free_doc_limit=free_doc_limit,
        free_question_limit=free_question_limit,
        razorpay_key_id=key_id,
        razorpay_key_secret=key_secret,
        razorpay_webhook_secret=webhook_secret,
        allow_guest_upload=False,
    )
    embedder = FastAlignedEmbedder()
    store = NumpyStore(dim=64)
    llm = MockDeterministicLLM()
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
        free_doc_limit=free_doc_limit,
        free_question_limit=free_question_limit,
    )
    app.state.auth_manager = auth_mgr
    app.state.razorpay_manager = RazorpayManager(
        key_id=key_id,
        key_secret=key_secret,
        webhook_secret=webhook_secret,
    )
    return app, auth_mgr, llm


# ==============================================================================
# 1. AUTHENTICATION & ACCESS CONTROL TESTS
# ==============================================================================


def test_anonymous_access_and_registration_lifecycle(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(tmp_path)
    client = TestClient(app)

    # 1. Unauthenticated request to workspace endpoints without cookies/session returns 401
    resp = client.get("/api/demo/documents")
    assert resp.status_code == 401

    resp = client.get("/api/auth/profile")
    assert resp.status_code == 401

    # 2. Register account
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "StrongPassword123!"},
    )
    assert reg_resp.status_code in (200, 201)
    user_data = reg_resp.json()
    assert user_data["user"]["email"] == "alice@example.com"
    user_id = user_data["user"]["id"]

    # 3. Quota record initialized automatically with free tier (1 doc, 5 questions)
    quota = auth_mgr.get_user_quota(user_id)
    assert quota["plan_id"] == "free"
    assert quota["doc_limit"] == 1
    assert quota["consumed_docs"] == 0
    assert quota["question_limit"] == 5
    assert quota["consumed_questions"] == 0

    # 4. /api/auth/me returns authenticated status and quota details
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["authenticated"] is True
    assert me_data["quota"]["consumed_docs"] == 0

    # 5. Invalid credentials rejected
    client_unauth = TestClient(app)
    bad_login = client_unauth.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "WrongPassword!"},
    )
    assert bad_login.status_code in {400, 401}

    # 6. Logout invalidates session
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    me_after = client.get("/api/auth/me")
    assert me_after.json()["authenticated"] is False


# ==============================================================================
# 2. DOCUMENT QUOTA TESTS (1 LIFETIME DOCUMENT)
# ==============================================================================


def test_free_document_limit_one_document_lifetime(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(tmp_path, free_doc_limit=1)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "PasswordBob123!"},
    )

    # 1. First upload succeeds
    doc1 = b"DocuMind verifiable intelligence document content."
    up1 = client.post(
        "/api/demo/documents",
        files={"file": ("manual.txt", io.BytesIO(doc1), "text/plain")},
    )
    assert up1.status_code == 201
    assert up1.json()["status"] == "indexed"
    assert up1.json()["chunk_count"] > 0

    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_docs"] == 1

    # 2. Second upload rejected with FREE_DOCUMENT_LIMIT_REACHED (403)
    doc2 = b"Second document content that exceeds allowance."
    up2 = client.post(
        "/api/demo/documents",
        files={"file": ("extra.txt", io.BytesIO(doc2), "text/plain")},
    )
    assert up2.status_code == 403
    err_body = up2.json()
    assert err_body["code"] == "FREE_DOCUMENT_LIMIT_REACHED"
    assert "upgrade_url" in err_body
    assert err_body["quota"]["consumed_docs"] == 1

    # 3. Deletion of first document does NOT restore the lifetime allowance
    del_resp = client.delete("/api/demo/documents/manual.txt")
    assert del_resp.status_code == 204

    # Quota is still consumed (lifetime policy)
    quota_after_del = client.get("/api/auth/quota").json()["quota"]
    assert quota_after_del["consumed_docs"] == 1

    # Attempting to upload again is still rejected
    up3 = client.post(
        "/api/demo/documents",
        files={"file": ("manual.txt", io.BytesIO(doc1), "text/plain")},
    )
    assert up3.status_code == 403
    assert up3.json()["code"] == "FREE_DOCUMENT_LIMIT_REACHED"


def test_failed_upload_does_not_consume_document_quota(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(tmp_path, free_doc_limit=1)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "charlie@example.com", "password": "PasswordCharlie123!"},
    )

    # Upload invalid unsupported file type (.exe)
    bad_up = client.post(
        "/api/demo/documents",
        files={"file": ("malicious.exe", io.BytesIO(b"binary data"), "application/octet-stream")},
    )
    assert bad_up.status_code == 415

    # Quota was NOT consumed
    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_docs"] == 0

    # User can still upload valid document
    good_up = client.post(
        "/api/demo/documents",
        files={"file": ("good.txt", io.BytesIO(b"Valid document text."), "text/plain")},
    )
    assert good_up.status_code == 201
    assert good_up.json()["status"] == "indexed"

    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_docs"] == 1


def test_concurrent_upload_race_condition_safe(tmp_path: Path):
    """Verify concurrency safety: parallel uploads cannot both consume a single quota slot."""
    app, auth_mgr, _ = build_saas_app(tmp_path, free_doc_limit=1)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "parallel@example.com", "password": "ParallelPassword123!"},
    )

    def do_upload(name: str):
        c = TestClient(app, cookies=client.cookies)
        content = f"Concurrent document content for {name}.".encode()
        return c.post(
            "/api/demo/documents",
            files={"file": (f"{name}.txt", io.BytesIO(content), "text/plain")},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        f1 = executor.submit(do_upload, "file_a")
        f2 = executor.submit(do_upload, "file_b")
        f3 = executor.submit(do_upload, "file_c")
        results = [f1.result(), f2.result(), f3.result()]

    successes = [r for r in results if r.status_code == 201]
    rejections = [r for r in results if r.status_code == 403]

    # Exactly ONE must succeed and the others must be rejected with 403
    assert len(successes) == 1
    assert len(rejections) == 2
    for rej in rejections:
        assert rej.json()["code"] == "FREE_DOCUMENT_LIMIT_REACHED"

    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_docs"] == 1


# ==============================================================================
# 3. QUESTION QUOTA TESTS (5 LIFETIME QUESTIONS)
# ==============================================================================


def test_five_question_allowance_enforcement(tmp_path: Path):
    app, auth_mgr, mock_llm = build_saas_app(tmp_path, free_doc_limit=1, free_question_limit=5)
    client = TestClient(app)

    # Register & upload 1 document
    client.post(
        "/api/auth/register",
        json={"email": "questions@example.com", "password": "PasswordQuestions123!"},
    )
    doc_content = b"DocuMind architecture uses hybrid lexical vector retrieval."
    client.post(
        "/api/demo/documents",
        files={"file": ("doc.txt", io.BytesIO(doc_content), "text/plain")},
    )

    # Create conversation
    conv_res = client.post("/api/demo/conversations", json={"title": "Test Chat"})
    conv_id = conv_res.json()["id"]

    # 1. Questions 1 through 5 succeed
    for i in range(1, 6):
        chat_resp = client.post(
            "/api/demo/chat",
            json={"conversation_id": conv_id, "question": f"Question {i}?"},
        )
        assert chat_resp.status_code == 200
        quota = client.get("/api/auth/quota").json()["quota"]
        assert quota["consumed_questions"] == i
        assert quota["reserved_questions"] == 0

    calls_after_5 = mock_llm.call_count
    assert calls_after_5 > 0

    # 2. Question 6 is rejected with FREE_QUESTION_LIMIT_REACHED (403) BEFORE LLM is invoked
    chat_resp_6 = client.post(
        "/api/demo/chat",
        json={"conversation_id": conv_id, "question": "Question 6?"},
    )
    assert chat_resp_6.status_code == 403
    err_body = chat_resp_6.json()
    assert err_body["code"] == "FREE_QUESTION_LIMIT_REACHED"
    assert "upgrade_url" in err_body

    # Critical cost control check: LLM call count must remain completely frozen!
    assert mock_llm.call_count == calls_after_5

    # Quota remains at 5 consumed, 0 reserved
    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_questions"] == 5

    # 3. New conversation does NOT grant new credits
    conv_res2 = client.post("/api/demo/conversations", json={"title": "New Chat Thread"})
    conv_id2 = conv_res2.json()["id"]
    bypass_attempt = client.post(
        "/api/demo/chat",
        json={"conversation_id": conv_id2, "question": "Can I bypass in new chat?"},
    )
    assert bypass_attempt.status_code == 403
    assert bypass_attempt.json()["code"] == "FREE_QUESTION_LIMIT_REACHED"
    assert mock_llm.call_count == calls_after_5

    # 4. Relogging in does NOT grant new credits
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "questions@example.com", "password": "PasswordQuestions123!"},
    )
    relog_attempt = client.post(
        "/api/demo/chat",
        json={"conversation_id": conv_id, "question": "After relogin?"},
    )
    assert relog_attempt.status_code == 403
    assert relog_attempt.json()["code"] == "FREE_QUESTION_LIMIT_REACHED"


def test_genuine_abstention_counts_towards_question_quota(tmp_path: Path):
    """A genuine relevance-gate abstention counts as a question because retrieval occurred."""
    app, auth_mgr, _ = build_saas_app(tmp_path, free_doc_limit=1, free_question_limit=5)
    client = TestClient(app)

    client.post(
        "/api/auth/register",
        json={"email": "abstain_user@example.com", "password": "PasswordAbstain123!"},
    )
    client.post(
        "/api/demo/documents",
        files={"file": ("facts.txt", io.BytesIO(b"DocuMind software facts."), "text/plain")},
    )

    # Query with irrelevant question that triggers relevance gate abstention
    res = client.post(
        "/api/demo/chat",
        json={"question": "irrelevant aliens quantum cooking recipe"},
    )
    assert res.status_code == 200

    # Processed query counted towards quota
    quota = client.get("/api/auth/quota").json()["quota"]
    assert quota["consumed_questions"] == 1


# ==============================================================================
# 4. SUBSCRIPTION, RAZORPAY CHECKOUT & WEBHOOK TESTS
# ==============================================================================


def test_plans_endpoint_and_checkout_generation(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(tmp_path)
    client = TestClient(app)

    # 1. GET /api/billing/plans returns configured plans with exact prices and caps
    plans_resp = client.get("/api/billing/plans")
    assert plans_resp.status_code == 200
    plans = plans_resp.json()["plans"]
    assert len(plans) >= 3

    plan_ids = [p["plan_id"] for p in plans]
    assert "free" in plan_ids
    assert "pro_monthly" in plan_ids
    assert "team_monthly" in plan_ids

    pro_plan = next(p for p in plans if p["plan_id"] == "pro_monthly")
    assert pro_plan["price_cents"] == 99900  # ₹999 in paise
    assert pro_plan["currency"] == "INR"
    assert pro_plan["doc_limit"] == 50
    assert pro_plan["question_limit"] == 500

    # 2. Checkout generation requires authentication
    unauth_client = TestClient(app)
    unauth_checkout = unauth_client.post("/api/billing/checkout", json={"plan_id": "pro_monthly"})
    assert unauth_checkout.status_code == 401

    # 3. Authenticated checkout generation
    client.post(
        "/api/auth/register",
        json={"email": "subscriber@example.com", "password": "PasswordSub123!"},
    )
    checkout_res = client.post("/api/billing/checkout", json={"plan_id": "pro_monthly"})
    assert checkout_res.status_code == 200
    c_data = checkout_res.json()
    assert c_data["status"] == "checkout_ready"
    assert c_data["plan_id"] == "pro_monthly"
    assert c_data["amount"] == 99900
    assert c_data["currency"] == "INR"
    assert "order_id" in c_data or "subscription_id" in c_data


def test_payment_verification_and_plan_upgrade(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(
        tmp_path,
        key_id="rzp_test_12345678",
        key_secret="secret_key_for_hmac_sha256_32char",  # noqa: S106
    )
    client = TestClient(app)

    reg_res = client.post(
        "/api/auth/register",
        json={"email": "payer@example.com", "password": "PasswordPayer123!"},
    )
    user_id = reg_res.json()["user"]["id"]

    checkout = client.post("/api/billing/checkout", json={"plan_id": "pro_monthly"}).json()
    order_id = checkout.get("order_id")
    test_sig = checkout.get("test_signature")

    # 1. Invalid signature is rejected (no upgrade)
    bad_verify = client.post(
        "/api/billing/verify",
        json={
            "plan_id": "pro_monthly",
            "order_id": order_id,
            "payment_id": "pay_fake_123",
            "signature": "forged_signature_that_does_not_match",
        },
    )
    assert bad_verify.status_code == 400
    assert auth_mgr.get_user_quota(user_id)["plan_id"] == "free"

    # 2. Valid signature verifies and upgrades plan
    good_verify = client.post(
        "/api/billing/verify",
        json={
            "plan_id": "pro_monthly",
            "order_id": order_id,
            "payment_id": "pay_test_valid_123",
            "signature": test_sig,
        },
    )
    assert good_verify.status_code == 200
    v_data = good_verify.json()
    assert v_data["status"] == "ok"
    assert v_data["quota"]["plan_id"] == "pro_monthly"
    assert v_data["quota"]["doc_limit"] == 50
    assert v_data["quota"]["question_limit"] == 500

    # User can now upload a second document (quota expanded)
    up2 = client.post(
        "/api/demo/documents",
        files={"file": ("pro_doc2.txt", io.BytesIO(b"Second doc on Pro plan."), "text/plain")},
    )
    assert up2.status_code == 201


def test_webhook_cryptographic_verification_and_replay_protection(tmp_path: Path):
    webhook_secret = "rzp_webhook_secret_key_super_secure"  # noqa: S105
    app, auth_mgr, _ = build_saas_app(tmp_path, webhook_secret=webhook_secret)
    client = TestClient(app)

    reg = client.post(
        "/api/auth/register",
        json={"email": "webhook_user@example.com", "password": "PasswordWebhook123!"},
    )
    user_id = reg.json()["user"]["id"]

    event_payload = {
        "entity": "event",
        "account_id": "acc_mock_123",
        "event": "subscription.activated",
        "id": "evt_test_unique_webhook_id_001",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test_98765",
                    "plan_id": "plan_test_pro",
                    "status": "active",
                    "notes": {
                        "user_id": user_id,
                        "plan_id": "pro_monthly",
                    },
                }
            }
        },
        "created_at": int(time.time()),
    }
    raw_body = json.dumps(event_payload).encode("utf-8")

    rzp_mgr = app.state.razorpay_manager
    valid_sig = rzp_mgr.compute_webhook_signature(raw_body)

    # 1. Invalid signature rejected with 400
    bad_headers = {"X-Razorpay-Signature": "invalid_signature"}
    res_bad = client.post("/api/billing/webhook", content=raw_body, headers=bad_headers)
    assert res_bad.status_code == 400

    # 2. Valid signature processes event and upgrades plan
    good_headers = {"X-Razorpay-Signature": valid_sig}
    res_good = client.post("/api/billing/webhook", content=raw_body, headers=good_headers)
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "ok"

    quota = auth_mgr.get_user_quota(user_id)
    assert quota["plan_id"] == "pro_monthly"
    assert quota["doc_limit"] == 50

    # 3. Idempotent replay protection: second delivery returns already_processed
    res_replay = client.post("/api/billing/webhook", content=raw_body, headers=good_headers)
    assert res_replay.status_code == 200
    assert res_replay.json()["status"] == "already_processed"


def test_subscription_cancellation_lifecycle(tmp_path: Path):
    app, auth_mgr, _ = build_saas_app(tmp_path)
    client = TestClient(app)

    reg = client.post(
        "/api/auth/register",
        json={"email": "canceller@example.com", "password": "PasswordCanceller123!"},
    )
    user_id = reg.json()["user"]["id"]

    # Upgrade to pro
    auth_mgr.upgrade_user_plan(
        user_id=user_id,
        new_plan_id="pro_monthly",
        doc_limit=50,
        question_limit=500,
        subscription_id="sub_test_cancel_1",
    )

    # Cancel subscription
    cancel_res = client.post("/api/billing/subscription/cancel", json={"reason": "too_expensive"})
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "ok"

    sub = auth_mgr.get_user_subscription(user_id)
    assert sub["status"] == "cancelled"
    assert sub["cancel_at_period_end"] == 1

    # End-of-period expiration degrades user to free plan
    auth_mgr.expire_user_subscription(user_id)
    quota_after = auth_mgr.get_user_quota(user_id)
    assert quota_after["plan_id"] == "free"
    assert quota_after["doc_limit"] == 1


# ==============================================================================
# 5. PERSISTENCE & DEPLOYMENT SURVIVABILITY TESTS
# ==============================================================================


def test_quotas_survive_application_restart(tmp_path: Path):
    """Verify user quotas, consumed counts, and subscription records persist across app restart."""
    # Run App Instance 1
    app1, auth_mgr1, _ = build_saas_app(tmp_path, free_doc_limit=1, free_question_limit=5)
    c1 = TestClient(app1)

    reg = c1.post(
        "/api/auth/register",
        json={"email": "persistent@example.com", "password": "PasswordPersist123!"},
    )
    user_id = reg.json()["user"]["id"]

    # Upload 1 doc and consume 2 questions
    c1.post(
        "/api/demo/documents",
        files={"file": ("persist.txt", io.BytesIO(b"Persistent intelligence data."), "text/plain")},
    )
    c1.post("/api/demo/chat", json={"question": "Question 1?"})
    c1.post("/api/demo/chat", json={"question": "Question 2?"})

    quota1 = auth_mgr1.get_user_quota(user_id)
    assert quota1["consumed_docs"] == 1
    assert quota1["consumed_questions"] == 2

    # Simulate App Restart / redeployment: Create fresh App Instance 2 against same DB
    app2, auth_mgr2, _ = build_saas_app(tmp_path, free_doc_limit=1, free_question_limit=5)
    c2 = TestClient(app2)

    # Login on fresh instance
    login_res = c2.post(
        "/api/auth/login",
        json={"email": "persistent@example.com", "password": "PasswordPersist123!"},
    )
    assert login_res.status_code == 200

    quota2 = c2.get("/api/auth/quota").json()["quota"]
    assert quota2["consumed_docs"] == 1
    assert quota2["consumed_questions"] == 2

    # Attempting to upload on new instance is still rejected (lifetime allowance preserved)
    up_again = c2.post(
        "/api/demo/documents",
        files={"file": ("another.txt", io.BytesIO(b"Another doc text."), "text/plain")},
    )
    assert up_again.status_code == 403
    assert up_again.json()["code"] == "FREE_DOCUMENT_LIMIT_REACHED"


def test_guest_upload_prohibited_without_login(tmp_path: Path):
    """Verify that uploading documents without logging in or registering is prohibited."""
    app, _, _ = build_saas_app(tmp_path)
    client = TestClient(app)

    # 1. Anonymous request without session token -> 401
    files = {"file": ("unauth.txt", io.BytesIO(b"Secret text"), "text/plain")}
    res_no_sess = client.post("/api/demo/documents", files=files)
    assert res_no_sess.status_code == 401

    # 2. Guest session token without login/registration -> 401
    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sess_id = sess_res.json()["session_id"]

    res_guest = client.post(
        "/api/demo/documents",
        headers={"X-Session-ID": sess_id},
        files=files,
    )
    assert res_guest.status_code == 401
    assert "Authentication required" in res_guest.text
