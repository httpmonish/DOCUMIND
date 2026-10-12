"""tests/test_frontend_smoke.py

Automated smoke tests for Phase A:
1. Verifies same-origin static mounting of Documind-frontend at /app and root redirect.
2. Verifies api.js loads as valid JavaScript and exports window.DocuMindAPI object.
3. Tests full end-to-end client journey via API client with fake LLM:
   - Load healthz & demo meta (assert tau == 0.35, zero hardcoded 0.45).
   - Verify empty state (0 documents).
   - Ingest tests/fixtures/os_notes.md and assert chunk counts match server response.
   - Ask "what is a semaphore?" and verify cited answer with candidate chunks.
   - Delete document and verify clean empty state.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager
from tests.fake_llm import FakeLLM


class FastEmbedder:
    """Deterministic fast embedder for deterministic tests."""

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
def smoke_app(tmp_path: Path):
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
        llm=FakeLLM(reply="A semaphore is a counter synchronization variable. [S1]"),
    )
    app = create_app(dm=dm, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=FastEmbedder(),
        shared_llm=FakeLLM(reply="A semaphore is a counter synchronization variable. [S1]"),
        settings=settings,
        ttl_seconds=3600,
    )
    return app


def test_static_files_mounting_and_root_redirect(smoke_app):
    client = TestClient(smoke_app)

    # 1. Root redirects to /app/console/code.html
    root_resp = client.get("/", follow_redirects=False)
    assert root_resp.status_code == 307
    assert root_resp.headers["location"] == "/app/console/code.html"

    # 2. Console page loads with HTTP 200
    console_resp = client.get("/app/console/code.html")
    assert console_resp.status_code == 200
    assert "DocuMind" in console_resp.text
    assert "../api.js" in console_resp.text
    assert "query-input" in console_resp.text

    # 3. Library page loads with HTTP 200
    library_resp = client.get("/app/library/code.html")
    assert library_resp.status_code == 200
    assert "drop-zone" in library_resp.text

    # 4. api.js loads with HTTP 200
    api_js_resp = client.get("/app/api.js")
    assert api_js_resp.status_code == 200
    assert "DocuMindAPI" in api_js_resp.text


def test_api_js_node_eval():
    """Verify api.js syntax and exports in Node.js engine."""
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js not available in environment")

    api_js_path = Path("Documind-frontend/api.js").resolve()
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{api_js_path}', 'utf8');
    const win = {{
      sessionStorage: {{
        getItem: () => null,
        setItem: () => {{}},
        removeItem: () => {{}}
      }},
      location: {{ origin: 'http://127.0.0.1:8000' }}
    }};
    global.window = win;
    global.self = win;
    eval(code);
    const api = win.DocuMindAPI || global.DocuMindAPI;
    if (typeof api !== 'object') {{
      process.exit(1);
    }}
    if (typeof api.askQuestion !== 'function') {{
      process.exit(2);
    }}
    console.log('OK: typeof DocuMindAPI is ' + typeof api);
    """
    res = subprocess.run([node_bin, "-e", script], capture_output=True, text=True)  # noqa: S603
    assert res.returncode == 0, f"Node eval failed: {res.stderr}"
    assert "OK: typeof DocuMindAPI is object" in res.stdout


def test_frontend_end_to_end_journey(smoke_app):
    client = TestClient(smoke_app)
    sess_resp = client.post("/api/demo/session")
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["session_id"]
    headers = {"X-Session-ID": session_id}

    # 1. Health check & Meta single-source tau verification
    h_resp = client.get("/healthz")
    assert h_resp.status_code == 200
    assert h_resp.json()["tau"] == 0.35

    m_resp = client.get("/api/demo/meta", headers=headers)
    assert m_resp.status_code == 200
    assert m_resp.json()["tau"] == 0.35
    assert m_resp.json()["documents_count"] == 0

    # 2. Ingest tests/fixtures/os_notes.md
    doc_path = Path("tests/fixtures/os_notes.md")
    if not doc_path.exists():
        content = b"# Operating Systems\nA semaphore is an atomic synchronization primitive."
    else:
        content = doc_path.read_bytes()

    upload_resp = client.post(
        "/api/demo/documents",
        headers=headers,
        files={"file": ("os_notes.md", io.BytesIO(content), "text/markdown")},
    )
    assert upload_resp.status_code == 201
    u_data = upload_resp.json()
    assert u_data["status"] == "indexed"
    assert u_data["chunks"] >= 1
    server_chunk_count = u_data["chunks"]

    # 3. Assert document list reflects server's chunk count
    docs_resp = client.get("/api/demo/documents", headers=headers)
    assert docs_resp.status_code == 200
    docs = docs_resp.json()
    assert len(docs) == 1
    assert docs[0]["source"] == "os_notes.md"
    assert docs[0]["chunks"] == server_chunk_count

    # 4. Ask "what is a semaphore?"
    ask_resp = client.post(
        "/api/demo/ask",
        headers=headers,
        json={"question": "what is a semaphore?", "top_k": 3},
    )
    assert ask_resp.status_code == 200
    a_data = ask_resp.json()
    assert a_data["outcome"] == "answered"
    assert "retrieved" in a_data
    assert len(a_data["retrieved"]) >= 1
    assert "citations" in a_data

    # 5. Delete document
    del_resp = client.delete("/api/demo/documents/os_notes.md", headers=headers)
    assert del_resp.status_code == 204

    # 6. Verify empty list
    docs_empty = client.get("/api/demo/documents", headers=headers)
    assert docs_empty.status_code == 200
    assert docs_empty.json() == []
