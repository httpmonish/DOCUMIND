"""tests/mcp/test_behaviour.py
Functional behaviour tests for DocuMind MCP tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.vector_store import NumpyStore
from documind.interfaces.mcp_server import create_mcp_server
from tests.mcp.conftest import TEST_DOC_2, CorpusEmbedder


@pytest.mark.asyncio
async def test_search_happy_path(mcp_server):
    """Happy path search returns relevant cited results matching query."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        res = await session.call_tool(
            "search_documents",
            arguments={"query": TEST_DOC_2, "top_k": 3},
        )
        assert not res.isError
        # In FastMCP, structuredContent or text content in content[0]
        payload = json.loads(res.content[0].text)

        assert payload["outcome"] == "results"
        assert payload["threshold"] == 0.35
        assert payload["top_score"] is not None
        assert payload["top_score"] >= 0.35
        assert len(payload["results"]) > 0

        first_hit = payload["results"][0]
        assert first_hit["citation_label"] == "S1"
        assert first_hit["rank"] == 1
        assert first_hit["source"] == "os_intro.md"
        assert "semaphore" in first_hit["text"].lower()
        assert "untrusted document data" in payload["notice"].lower()


@pytest.mark.asyncio
async def test_search_off_topic_query_abstains(mcp_server):
    """Query with low cosine similarity triggers confidence gate and abstains."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        res = await session.call_tool(
            "search_documents",
            arguments={
                "query": "Quantum baking with ancient sourdough yeast in nebula.",
                "top_k": 5,
            },
        )
        assert not res.isError
        payload = json.loads(res.content[0].text)

        assert payload["outcome"] == "no_relevant_results"
        assert payload["results"] == []


@pytest.mark.asyncio
async def test_search_top_k_clamp(mcp_server):
    """top_k is clamped to range [1, 10]."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        # Query with top_k > 10
        res = await session.call_tool(
            "search_documents",
            arguments={"query": TEST_DOC_2, "top_k": 99},
        )
        assert not res.isError
        payload = json.loads(res.content[0].text)
        assert len(payload["results"]) <= 10


@pytest.mark.asyncio
async def test_search_over_long_query_rejected(mcp_server):
    """Query exceeding 2000 chars is rejected."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        overlong = "a" * 2001
        res = await session.call_tool(
            "search_documents",
            arguments={"query": overlong},
        )
        assert res.isError


@pytest.mark.asyncio
async def test_empty_index_outcome(tmp_path: Path):
    """Searching an empty index returns outcome='empty_index' without errors."""
    empty_store = NumpyStore(dim=384)
    engine = DocuMind(Settings(home=tmp_path), CorpusEmbedder(), empty_store, llm=None)
    empty_server = create_mcp_server(home=tmp_path, engine=engine)

    async with create_connected_server_and_client_session(empty_server._mcp_server) as session:
        await session.initialize()

        res = await session.call_tool(
            "search_documents",
            arguments={"query": "What is an operating system?"},
        )
        assert not res.isError
        payload = json.loads(res.content[0].text)
        assert payload["outcome"] == "empty_index"
        assert payload["results"] == []
        assert payload["top_score"] is None


@pytest.mark.asyncio
async def test_get_chunk_and_neighbors(mcp_server):
    """get_chunk retrieves chunk details along with adjacent neighbor chunks."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        # Target chunk 0001 (has preceding neighbor 0000)
        res = await session.call_tool(
            "get_chunk",
            arguments={"chunk_id": "os_intro.md_chunk_0001", "neighbors": 1},
        )
        assert not res.isError
        payload = json.loads(res.content[0].text)

        assert payload["chunk_id"] == "os_intro.md_chunk_0001"
        assert payload["source"] == "os_intro.md"
        assert payload["chunk_index"] == 1
        assert "semaphore" in payload["text"].lower()

        neighbors = payload["neighbors"]
        assert len(neighbors) == 1
        assert neighbors[0]["chunk_id"] == "os_intro.md_chunk_0000"
        assert neighbors[0]["chunk_index"] == 0
        assert neighbors[0]["relative_position"] == -1


@pytest.mark.asyncio
async def test_list_documents(mcp_server):
    """list_documents returns per-document chunk counts and short hashes."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        res = await session.call_tool("list_documents", arguments={})
        assert not res.isError
        payload = json.loads(res.content[0].text)

        assert payload["count"] == 2
        sources = {d["source"] for d in payload["documents"]}
        assert sources == {"os_intro.md", "memory.md"}

        for doc in payload["documents"]:
            assert doc["chunk_count"] == 2
            assert len(doc["content_hash"]) > 0


@pytest.mark.asyncio
async def test_index_info(mcp_server):
    """index_info returns global counts, embedder details, and DocuMind version."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        res = await session.call_tool("index_info", arguments={})
        assert not res.isError
        payload = json.loads(res.content[0].text)

        assert payload["document_count"] == 2
        assert payload["chunk_count"] == 4
        assert payload["embedder_name"] == "test-embedder"
        assert payload["dimensions"] == 384
        assert payload["tau"] == 0.35
        assert payload["store_type"] == "NumpyStore"
        assert payload["documind_version"] == "0.7.0"
