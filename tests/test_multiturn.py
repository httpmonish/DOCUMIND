"""tests/test_multiturn.py
Comprehensive unit and integration tests for Phase C:
- Multi-turn SQLite persistence (ChatManager)
- Follow-up query condensation (condense_query)
- Neighbor chunk expansion (expand_neighbors)
- REST and SSE streaming chat endpoints (/api/demo/chat, /api/demo/chat/stream)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from starlette.testclient import TestClient

from documind.core.chat import ChatManager
from documind.core.condense import condense_query, heuristic_condense, is_follow_up_query
from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.retrieval import expand_neighbors
from documind.core.types import Chunk, RetrievedChunk
from documind.core.vector_store import NumpyStore
from documind.interfaces.api import create_app
from documind.interfaces.session import SessionManager
from tests.fake_llm import FakeLLM


def test_chat_manager_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "chat_test.db"
    mgr = ChatManager(db_path)

    session_id = "test_sess_01"
    conv_id = mgr.create_conversation(session_id, title="Test Topic")
    assert conv_id

    # Verify conversation retrieved
    conv = mgr.get_conversation(conv_id)
    assert conv is not None
    assert conv["session_hash"] == session_id
    assert conv["title"] == "Test Topic"

    # Add messages
    m1 = mgr.add_message(conv_id, "user", "What is an OS?")
    m2 = mgr.add_message(
        conv_id,
        "assistant",
        "An OS manages hardware. [S1]",
        citations=[{"marker": "S1", "source": "os.txt", "chunk_index": 0}],
        retrieved=[{"id": "c1", "score": 0.85}],
        usage={"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.0001},
    )
    assert m1 and m2

    # Verify listing messages
    messages = mgr.get_messages(conv_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is an OS?"
    assert messages[1]["role"] == "assistant"
    assert len(messages[1]["citations"]) == 1
    assert messages[1]["citations"][0]["marker"] == "S1"
    assert messages[1]["usage"]["input_tokens"] == 100

    # Verify context turns extraction
    turns = mgr.get_context_turns(conv_id, max_turns=5)
    assert len(turns) == 2
    assert turns[0] == {"role": "user", "content": "What is an OS?"}
    assert turns[1] == {"role": "assistant", "content": "An OS manages hardware. [S1]"}

    # Update title
    assert mgr.update_conversation_title(conv_id, "Operating Systems 101")
    conv_updated = mgr.get_conversation(conv_id)
    assert conv_updated is not None
    assert conv_updated["title"] == "Operating Systems 101"

    # Verify conversation listing
    convs = mgr.list_conversations(session_id)
    assert len(convs) == 1
    assert convs[0]["id"] == conv_id
    assert convs[0]["message_count"] == 2

    # Delete conversation
    assert mgr.delete_conversation(conv_id)
    assert mgr.get_conversation(conv_id) is None
    assert len(mgr.get_messages(conv_id)) == 0


def test_condense_query_logic() -> None:
    history = [
        {"role": "user", "content": "What is mutual exclusion?"},
        {"role": "assistant", "content": "Mutual exclusion prevents race conditions."},
    ]

    # Follow-up query detection
    assert is_follow_up_query("how does it work?", history) is True
    assert is_follow_up_query("what about semaphores?", history) is True
    assert is_follow_up_query("why?", history) is True
    assert is_follow_up_query("Who won the FIFA World Cup?", history) is False

    # Heuristic condensation
    q_cond = heuristic_condense("how does it work?", history)
    assert "mutual exclusion" in q_cond.lower()

    # Query condensation with FakeLLM
    fake_llm = FakeLLM(reply="How does mutual exclusion operate in concurrent computing?")
    llm_cond = condense_query("how does it work?", history, llm=fake_llm)
    assert "mutual exclusion" in llm_cond.lower()

    # Query condensation fallback without history returns original question
    assert condense_query("Standalone question", []) == "Standalone question"


def test_neighbor_chunk_expansion() -> None:
    store = NumpyStore(dim=384)
    doc_chunks = [
        Chunk(
            id=f"guide.txt_chunk_{i:04d}",
            text=f"Paragraph {i} content",
            source="guide.txt",
            chunk_index=i,
            doc_sha256="abc123",
        )
        for i in range(5)
    ]
    store.upsert(doc_chunks, np.zeros((5, 384), dtype=np.float32))

    # Retrieve chunk index 2 (middle chunk)
    hit = RetrievedChunk(chunk=doc_chunks[2], score=0.92, rank=1)
    expanded = expand_neighbors([hit], store, max_top_to_expand=1)

    # Must contain chunk 2, and neighbors chunk 1 and chunk 3
    indices = [c.chunk.chunk_index for c in expanded]
    assert indices == [2, 1, 3]

    # Test edge boundary: chunk index 0 expands only to index 1
    hit_0 = RetrievedChunk(chunk=doc_chunks[0], score=0.88, rank=1)
    expanded_0 = expand_neighbors([hit_0], store, max_top_to_expand=1)
    indices_0 = [c.chunk.chunk_index for c in expanded_0]
    assert indices_0 == [0, 1]


def test_chat_rest_and_streaming_e2e(tmp_path: Path) -> None:
    settings = Settings(
        home=tmp_path / "home",
        chunk_size=200,
        overlap=50,
        top_k=3,
        min_score=0.20,
    )

    class TestEmbedder:
        model_id = "test-embedder"
        dim = 4

        def embed_query(self, text: str) -> np.ndarray:
            v = np.zeros(4, dtype=np.float32)
            v[0] = 1.0
            return v

        def embed_documents(self, texts: list[str]) -> np.ndarray:
            arr = np.zeros((len(texts), 4), dtype=np.float32)
            for i in range(len(texts)):
                arr[i, 0] = 1.0
            return arr

    embedder = TestEmbedder()
    store = NumpyStore(dim=4)
    llm = FakeLLM(reply="Semaphores prevent race conditions [S1].")
    engine = DocuMind(settings, embedder, store, llm)
    app = create_app(dm=engine, settings=settings)
    app.state.session_manager = SessionManager(
        base_dir=settings.home / "sessions",
        shared_embedder=embedder,
        shared_llm=llm,
        settings=settings,
    )
    app.state.chat_manager = ChatManager(settings.home / "chat.db")
    client = TestClient(app)

    # 1. Acquire session
    sess_resp = client.post("/api/demo/session")
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["session_id"]
    headers = {"X-Session-ID": session_id}

    # Index text in session engine
    session_engine, _ = app.state.session_manager.get_engine(session_id)
    session_engine.index_text(
        "Semaphores are synchronization primitives. They prevent race conditions.",
        source="os_sync.txt",
        sha256="abc123456",
    )

    # 2. Test POST /api/demo/chat
    chat_resp = client.post(
        "/api/demo/chat",
        headers=headers,
        json={"question": "What is a semaphore?"},
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()
    assert data["outcome"] == "answered"
    assert "conversation_id" in data
    conv_id = data["conversation_id"]

    # Verify conversation created in SQLite
    convs_resp = client.get("/api/demo/conversations", headers=headers)
    assert convs_resp.status_code == 200
    convs = convs_resp.json()
    assert len(convs) >= 1
    assert convs[0]["id"] == conv_id

    # 3. Test follow-up question via POST /api/demo/chat/stream SSE
    stream_resp = client.post(
        "/api/demo/chat/stream",
        headers=headers,
        json={"conversation_id": conv_id, "question": "how do they work?"},
    )
    assert stream_resp.status_code == 200
    assert "text/event-stream" in stream_resp.headers["content-type"]

    # Parse SSE events
    raw_lines = stream_resp.text.strip().split("\n\n")
    events = {}
    tokens = []
    for block in raw_lines:
        lines = block.strip().split("\n")
        ev_name = None
        ev_data = None
        for line in lines:
            if line.startswith("event: "):
                ev_name = line[len("event: ") :]
            elif line.startswith("data: "):
                ev_data = json.loads(line[len("data: ") :])
        if ev_name:
            if ev_name == "token":
                tokens.append(ev_data.get("delta", ""))
            else:
                events[ev_name] = ev_data

    # Check SSE contract events
    assert "meta" in events
    assert events["meta"]["conversation_id"] == conv_id
    assert "retrieval" in events
    assert isinstance(events["retrieval"]["retrieved"], list)
    assert len(tokens) > 0
    assert "citations" in events
    assert "done" in events
    assert events["done"]["outcome"] == "answered"

    # Verify message history contains 4 turns (2 user, 2 assistant)
    msgs_resp = client.get(f"/api/demo/conversations/{conv_id}/messages", headers=headers)
    assert msgs_resp.status_code == 200
    msgs = msgs_resp.json()
    assert len(msgs) == 4
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    assert msgs[3]["role"] == "assistant"
