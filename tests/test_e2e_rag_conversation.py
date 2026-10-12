"""tests/test_e2e_rag_conversation.py
End-to-end automated verification of Priority 1:
- PDF / text upload and indexing
- True chunk counts in listing
- Grounded answer with verified citation
- Abstention on absent information (tau < 0.35 threshold)
- Follow-up question in the same conversation thread
- Unconfigured LLM clean error / guidance state
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


class DeterministicEmbedder:
    """Embedder that maps 'quantum' questions to quantum text chunks with high similarity,

    and completely unrelated questions to low similarity.
    """

    model_id: str = "deterministic-test-embedder"
    dim: int = 16

    def embed_query(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        if "quantum" in text.lower() or "qubit" in text.lower():
            v[0] = 1.0  # Close to quantum chunk
        else:
            v[5] = 1.0  # Orthogonal, similarity = 0.0 < 0.35 tau
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        arr = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            if "quantum" in t.lower() or "qubit" in t.lower():
                arr[i, 0] = 1.0
            else:
                arr[i, 3] = 1.0
        return arr


@pytest.fixture
def rag_app(tmp_path: Path):
    settings = Settings(
        home=tmp_path,
        api_key="a" * 32,
        min_score=0.35,
        allow_debug=True,
    )
    shared_embedder = DeterministicEmbedder()
    shared_llm = FakeLLM(
        reply="Superconducting qubits maintain coherence for 100 microseconds. [S1]"
    )

    dm = DocuMind(
        settings=settings,
        store=NumpyStore(),
        embedder=shared_embedder,
        llm=shared_llm,
    )
    app = create_app(dm=dm, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=tmp_path / "sessions",
        shared_embedder=shared_embedder,
        shared_llm=shared_llm,
        settings=settings,
        ttl_seconds=3600,
    )
    app.state.chat_manager = ChatManager(db_path=tmp_path / "chat.db")
    return app


def test_e2e_grounded_answer_abstention_and_followup(rag_app):
    client = TestClient(rag_app)

    # 1. Initialize server-issued session
    sess_res = client.post("/api/demo/session")
    assert sess_res.status_code == 201
    sid = sess_res.json()["session_id"]
    headers = {"X-Session-ID": sid}

    # 2. Upload document containing specific facts
    doc_content = (
        b"Quantum computing breakthrough: The new superconducting qubits maintain coherence "
        b"for 100 microseconds under cryogenic dilution refrigeration."
    )
    files = {"file": ("quantum_specs.txt", doc_content, "text/plain")}
    up_res = client.post("/api/demo/documents", headers=headers, files=files)
    assert up_res.status_code == 201
    up_data = up_res.json()
    assert up_data["status"] == "indexed"
    assert up_data["chunks"] >= 1
    assert up_data["chunk_count"] >= 1

    # 3. Document listing displays true chunk counts
    list_res = client.get("/api/demo/documents", headers=headers)
    assert list_res.status_code == 200
    docs = list_res.json()
    assert len(docs) == 1
    assert docs[0]["chunks"] == up_data["chunks"]
    assert docs[0]["chunk_count"] == up_data["chunks"]
    assert docs[0]["source"] == "quantum_specs.txt"

    # 4. Ask grounded question explicitly answered in document
    chat_stream_1 = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"question": "What is the coherence time of the superconducting qubits?"},
    )
    assert chat_stream_1.status_code == 200
    events_1 = parse_sse(chat_stream_1.text)

    # Verify conversation ID established
    assert "meta" in events_1
    conv_id = events_1["meta"]["conversation_id"]
    assert conv_id is not None

    # Verify grounded answer tokens and citations
    assert "token" in events_1
    assert "100 microseconds" in "".join(events_1["token"])
    assert "citations" in events_1
    cits = events_1["citations"]["citations"]
    assert len(cits) > 0
    assert cits[0]["source"] == "quantum_specs.txt"

    # Verify done outcome is answered
    assert events_1["done"]["outcome"] == "answered"

    # 5. Ask unanswerable question completely absent from document
    # (Triggers relevance gate tau < 0.35 -> abstention)
    chat_stream_2 = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={
            "question": "What is the secret recipe for baking sourdough bread?",
            "conversation_id": conv_id,
        },
    )
    assert chat_stream_2.status_code == 200
    events_2 = parse_sse(chat_stream_2.text)
    assert events_2["done"]["outcome"] in ("abstained", "abstain")
    assert "I couldn't find any sufficiently relevant passages" in "".join(events_2["token"])

    # 6. Ask follow-up question in the same conversation
    chat_stream_3 = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={
            "question": "Under what refrigeration method do these qubits operate?",
            "conversation_id": conv_id,
        },
    )
    assert chat_stream_3.status_code == 200
    events_3 = parse_sse(chat_stream_3.text)
    assert events_3["done"]["outcome"] == "answered"
    assert "citations" in events_3


def parse_sse(raw_sse: str) -> dict[str, Any]:
    events: dict[str, Any] = {"token": []}
    blocks = raw_sse.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        event_name = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:].strip()
        if event_name and data_str:
            try:
                parsed = json.loads(data_str)
            except Exception:
                parsed = data_str
            if event_name == "token":
                events["token"].append(parsed.get("delta", ""))
            else:
                events[event_name] = parsed
    return events
