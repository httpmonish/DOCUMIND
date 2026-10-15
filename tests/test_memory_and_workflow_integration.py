"""tests/test_memory_and_workflow_integration.py
End-to-end integration test validating realistic user workflow:
- User authentication & login
- PDF document upload & isolated text extraction
- Vector indexing into ChromaDB / vector store
- Semantic retrieval & ranking
- Grounded RAG answer generation with citations
- Multi-turn conversation and chat history persistence
- Runtime memory monitoring across workflow stages
"""

from __future__ import annotations

import importlib
import io
import resource
import sys
from pathlib import Path

import numpy as np
import pytest
import tomllib
from pypdf import PdfReader, PdfWriter
from starlette.testclient import TestClient

from documind.core.chat import ChatManager
from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Usage
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.auth import AuthManager
from documind.interfaces.session import SessionManager


def _get_rss_mb() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024


class IntegrationTestLLM:
    model_id = "test-workflow-llm"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            "DocuMind provides grounded answers from uploaded PDF documents. [S1]",
            Usage(input_tokens=120, output_tokens=30),
        )


class IntegrationTestEmbedder:
    model_id = "BAAI/bge-small-en-v1.5"
    dim = 384

    def embed_query(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        vec[0] = 1.0
        return vec

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        arr[:, 0] = 1.0
        return arr


def test_full_workflow_login_upload_index_retrieval_citations_chathistory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate full end-to-end workflow without regression."""
    mem_start = _get_rss_mb()

    settings = Settings(
        home=tmp_path,
        api_key="integration_test_secret_key_32_characters!",
        require_auth=True,
        llm_provider="openai_compat",
        max_upload_mb=10,
        max_pages=20,
    )

    embedder = IntegrationTestEmbedder()
    store = NumpyStore(dim=384)
    llm = IntegrationTestLLM()
    engine = DocuMind(settings=settings, embedder=embedder, store=store, llm=llm)

    app = create_app(dm=engine, settings=settings)
    app.state.auth_manager = AuthManager(
        db_path=tmp_path / "auth.db",
        database_url="",
        free_doc_limit=10,
        free_question_limit=50,
    )
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=embedder,
        shared_llm=llm,
        settings=settings,
    )
    app.state.chat_manager = ChatManager(tmp_path / "chat.db")

    client = TestClient(app)

    # 1. User Registration & Login
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "StrongPassword123!",
            "display_name": "Integration User",
        },
    )
    assert reg_resp.status_code == 201, reg_resp.text
    assert "documind_auth_session" in client.cookies

    # Verify session profile
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is True
    assert me_resp.json()["user"]["email"] == "user@example.com"

    # 2. PDF Document Creation & Upload
    fixture_pdf = Path("tests/fixtures/hello.pdf")
    reader = PdfReader(str(fixture_pdf))
    writer = PdfWriter()
    # Create a 3-page test PDF
    for _ in range(3):
        writer.add_page(reader.pages[0])
    pdf_buf = io.BytesIO()
    writer.write(pdf_buf)
    pdf_bytes = pdf_buf.getvalue()

    upload_headers = {"X-API-Key": settings.api_key}
    upload_resp = client.post(
        "/v1/documents",
        files={"file": ("workflow_doc.pdf", pdf_bytes, "application/pdf")},
        headers=upload_headers,
    )
    assert upload_resp.status_code == 201, upload_resp.text
    upload_data = upload_resp.json()
    assert upload_data["status"] == "indexed"
    assert upload_data["source"] == "workflow_doc.pdf"
    assert upload_data["chunks"] >= 1

    # 3. Vector Indexing Verification
    assert engine.store.count_for("workflow_doc.pdf") >= 1
    chunks_resp = client.get("/v1/documents/workflow_doc.pdf/chunks", headers=upload_headers)
    assert chunks_resp.status_code == 200
    assert len(chunks_resp.json()) >= 1

    # 4. Semantic Search / Retrieval via Engine and API
    search_results = engine.search("Hello world from PDF", top_k=3)
    assert len(search_results) >= 1
    assert search_results[0].chunk.source == "workflow_doc.pdf"

    # 5. Question Answering & Grounded Citations
    ask_resp = client.post(
        "/v1/ask",
        json={"question": "What does the PDF document discuss?"},
        headers=upload_headers,
    )
    assert ask_resp.status_code == 200, ask_resp.text
    ask_data = ask_resp.json()
    assert "text" in ask_data
    assert ask_data["outcome"] == "answered"
    assert len(ask_data["citations"]) >= 1
    assert ask_data["citations"][0]["source"] == "workflow_doc.pdf"

    # 6. Chat History & Conversation Tracking
    # Acquire a demo session
    demo_sess = client.post("/api/demo/session")
    assert demo_sess.status_code == 201
    sess_id = demo_sess.json()["session_id"]
    sess_headers = {"X-Session-ID": sess_id}

    user_id = me_resp.json()["user"]["id"]
    user_hash = app.state.auth_manager.get_user_workspace_hash(user_id)
    user_engine, _ = app.state.session_manager.get_engine(user_hash)
    user_engine.index_text(
        "DocuMind is an open source grounded document question answering engine.",
        source="documind_guide.txt",
        sha256="abc987654321",
    )

    # First turn chat
    chat_resp1 = client.post(
        "/api/demo/chat",
        headers=sess_headers,
        json={"question": "What is DocuMind?"},
    )
    assert chat_resp1.status_code == 200, chat_resp1.text
    chat_data1 = chat_resp1.json()
    assert chat_data1["outcome"] == "answered"
    assert "conversation_id" in chat_data1
    conv_id = chat_data1["conversation_id"]

    # Verify conversation list
    convs_resp = client.get("/api/demo/conversations", headers=sess_headers)
    assert convs_resp.status_code == 200
    conv_list = convs_resp.json()
    assert any(c["id"] == conv_id for c in conv_list)

    # Verify conversation message history
    msgs_resp = client.get(f"/api/demo/conversations/{conv_id}/messages", headers=sess_headers)
    assert msgs_resp.status_code == 200
    messages = msgs_resp.json()
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is DocuMind?"
    assert messages[1]["role"] == "assistant"

    # 7. Memory Measurement Check
    mem_end = _get_rss_mb()
    print(f"\n[Realistic Workflow RSS] Start: {mem_start:.2f} MB | End: {mem_end:.2f} MB")


def test_vercel_entrypoint_and_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate Vercel entrypoint configuration and basic routing."""
    # Verify pyproject.toml [tool.vercel] section
    with Path("pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    vercel_cfg = data.get("tool", {}).get("vercel", {})
    entrypoint_str = vercel_cfg.get("entrypoint")
    assert entrypoint_str in ("documind.interfaces.api", "documind.interfaces.api:app")

    # Dynamically resolve entrypoint module and attribute as Vercel does
    mod_name = entrypoint_str.split(":")[0]
    app_name = entrypoint_str.split(":")[1] if ":" in entrypoint_str else "app"
    mod = importlib.import_module(mod_name)
    app = getattr(mod, app_name)
    assert app is not None

    client = TestClient(app)

    # Healthcheck
    health_resp = client.get("/healthz")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"

    # Root redirect to frontend
    root_resp = client.get("/", follow_redirects=False)
    assert root_resp.status_code in (307, 308)
    assert "/app/console/code.html" in root_resp.headers["location"]

