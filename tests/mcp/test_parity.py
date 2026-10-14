"""tests/mcp/test_parity.py
Parity verification ensuring MCP search_documents produces identical
ranking, chunk IDs, and score fidelity compared to direct DocuMind engine search.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Chunk
from documind.core.vector_store import NumpyStore
from documind.interfaces.mcp_server import create_mcp_server
from tests.fake_embedder import FakeEmbedder

QUERIES = [
    "operating system hardware resource management",
    "semaphore integer counter shared resource synchronization",
    "virtual memory address space page frame mapping",
    "least recently used page replacement algorithm",
    "mutual exclusion lock primitive",
    "paging segmentation physical frame",
    "system call kernel user mode transition",
    "deadlock prevention bank algorithm",
    "multithreading race condition atomic operation",
    "file system inode allocation block pointer",
]


@pytest.fixture
def parity_corpus(tmp_path: Path):
    store = NumpyStore(dim=384)
    emb = FakeEmbedder()
    chunks = [
        Chunk(
            id=f"doc_{i:02d}.md_chunk_{j:04d}",
            text=f"Paragraph {j} discussing {q}. Explains details and mechanisms.",
            source=f"doc_{i:02d}.md",
            chunk_index=j,
            doc_sha256=f"hash_{i}_{j}",
        )
        for i, q in enumerate(QUERIES)
        for j in range(2)
    ]
    vectors = emb.embed_documents([c.text for c in chunks])
    store.upsert(chunks, vectors)

    settings = Settings(home=tmp_path, min_score=0.01)
    engine = DocuMind(settings, emb, store, llm=None)
    server = create_mcp_server(home=tmp_path, engine=engine)
    return engine, server


@pytest.mark.asyncio
async def test_ten_query_parity(parity_corpus):
    """Ensure search_documents matches direct engine.search() across 10 queries."""
    engine, server = parity_corpus

    async with create_connected_server_and_client_session(server._mcp_server) as session:
        await session.initialize()

        for query in QUERIES:
            # 1. Direct engine search
            engine_hits = engine.search(query, top_k=5)

            # 2. MCP tool search
            tool_res = await session.call_tool(
                "search_documents",
                arguments={"query": query, "top_k": 5},
            )
            assert not tool_res.isError
            payload = json.loads(tool_res.content[0].text)

            if not engine_hits or engine_hits[0].score < engine.settings.min_score:
                assert payload["outcome"] in ("no_relevant_results", "empty_index")
                assert payload["results"] == []
                continue

            assert payload["outcome"] == "results"
            mcp_hits = payload["results"]

            assert len(mcp_hits) == len(engine_hits)

            for rank, (m_hit, e_hit) in enumerate(zip(mcp_hits, engine_hits, strict=True), start=1):
                # Assert matching chunk IDs in exact same rank order
                assert m_hit["chunk_id"] == e_hit.chunk.id
                assert m_hit["rank"] == rank
                assert m_hit["chunk_index"] == e_hit.chunk.chunk_index
                assert Path(e_hit.chunk.source).name == m_hit["source"]

                # Assert scores match within 1e-6 of 4dp rounded value
                expected_score = round(float(e_hit.score), 4)
                assert abs(m_hit["score"] - expected_score) <= 1e-6
