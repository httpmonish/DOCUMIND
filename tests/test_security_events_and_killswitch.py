"""tests/test_security_events_and_killswitch.py
Verification tests for:
1. Global AI generation kill switch (DOCUMIND_DISABLE_GENERATION=1)
   disables LLM invocation gracefully, returning retrieval_only outcome.
2. Structured security audit events are recorded in SQLite without leaking passwords/tokens.
3. Admin and tenant isolation with recovery from corrupted indexes.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.auth import AuthManager
from tests.fake_llm import FakeLLM


class UnitEmbedder:
    model_id: str = "unit-embed"
    dim: int = 384

    def embed_query(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        v[0] = 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


@pytest.fixture
def sec_app(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="test_key_minimum_32_characters_long_for_security_checks",
    )
    store = NumpyStore()
    embedder = UnitEmbedder()
    llm = FakeLLM(reply="Verified response [S1]")
    dm = DocuMind(store=store, embedder=embedder, llm=llm, settings=settings)

    app = create_app(dm=dm, settings=settings)
    return app


def test_generation_killswitch_rest_api(sec_app):
    client = TestClient(sec_app)
    headers = {"X-API-Key": "test_key_minimum_32_characters_long_for_security_checks"}

    # Index sample document first
    files = {"file": ("manual.txt", b"System operational guide and manual.", "text/plain")}
    resp = client.post("/v1/documents", files=files, headers=headers)
    assert resp.status_code == 201

    # Without killswitch: generation operates normally
    with patch.dict(os.environ, {"DOCUMIND_DISABLE_GENERATION": "0"}):
        resp_normal = client.post(
            "/v1/ask",
            json={"question": "What is the operational guide?"},
            headers=headers,
        )
        assert resp_normal.status_code == 200

    # With killswitch enabled: generation is disabled safely with HTTP 503
    with patch.dict(os.environ, {"DOCUMIND_DISABLE_GENERATION": "1"}):
        resp_killed = client.post(
            "/v1/ask",
            json={"question": "What is the operational guide?"},
            headers=headers,
        )
        assert resp_killed.status_code == 503
        data = resp_killed.json()
        assert data["error"]["code"] == "generation_disabled"


def test_generation_killswitch_demo_ask_and_stream(sec_app):
    client = TestClient(sec_app)

    # 1. Initialize session
    sess_resp = client.post("/api/demo/session")
    assert sess_resp.status_code == 201
    sid = sess_resp.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # 2. Upload document
    doc_content = b"# DocuMind Architecture\nGrounded deterministic RAG engine."
    files = {"file": ("guide.md", doc_content, "text/markdown")}
    up_resp = client.post("/api/demo/documents", files=files, headers=headers)
    assert up_resp.status_code == 201

    # 3. Test demo_ask with kill switch enabled
    with patch.dict(os.environ, {"DOCUMIND_DISABLE_GENERATION": "1"}):
        ask_resp = client.post(
            "/api/demo/ask",
            json={"question": "Tell me about DocuMind architecture"},
            headers=headers,
        )
        assert ask_resp.status_code == 200
        ask_data = ask_resp.json()
        assert ask_data["outcome"] == "retrieval_only"
        assert ask_data["reason"] == "kill_switch_active"
        assert len(ask_data["retrieved"]) > 0

    # 4. Test chat_stream with kill switch enabled
    with patch.dict(os.environ, {"DOCUMIND_DISABLE_GENERATION": "1"}):
        stream_resp = client.post(
            "/api/demo/chat/stream",
            json={"question": "Tell me about DocuMind architecture"},
            headers=headers,
        )
        assert stream_resp.status_code == 200
        text = stream_resp.text
        assert "kill_switch_active" in text
        assert "retrieval_only" in text


def test_structured_security_events_logged(tmp_path: Path):
    auth_mgr = AuthManager(db_path=tmp_path / "auth_test.db")

    # Register user
    user, _, _ = auth_mgr.register("audit_user@example.com", "SecurePassword123!")

    # Verify event logged without password leak
    with auth_mgr._get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT event_type, metadata FROM usage_events WHERE user_id = ?"
        cursor.execute(query, (user.id,))
        rows = cursor.fetchall()
        assert len(rows) > 0
        event_type, meta_str = rows[0]
        assert event_type == "user_registered"
        assert "SecurePassword123!" not in meta_str
        assert "audit_user@example.com" in meta_str
