"""tests/mcp/conftest.py
Fixtures for MCP server tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Skip test suite if mcp is not installed
pytest.importorskip("mcp")

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import Chunk
from documind.core.vector_store import NumpyStore
from documind.interfaces.mcp_server import create_mcp_server
from tests.fake_embedder import FakeEmbedder

TEST_DOC_1 = "Operating systems manage hardware resources and coordinate application execution."
TEST_DOC_2 = "A semaphore is an integer counter used to synchronize access to shared memory."
TEST_DOC_3 = (
    "Virtual memory allows an operating system to address more memory than physically present."
)
TEST_DOC_4 = "Page replacement algorithms such as LRU select victim frames when memory is full."


class CorpusEmbedder(FakeEmbedder):
    """Embedder returning deterministic semantic vectors for fixture corpus."""

    model_id = "test-embedder"
    dim = 384


@pytest.fixture
def fixture_store() -> NumpyStore:
    """Populate an in-memory NumpyStore with 4 sequential chunks across 2 documents."""
    store = NumpyStore(dim=384)
    emb = CorpusEmbedder()

    chunks = [
        Chunk(
            id="os_intro.md_chunk_0000",
            text=TEST_DOC_1,
            source="os_intro.md",
            chunk_index=0,
            doc_sha256="abc1234567890abcdef",
        ),
        Chunk(
            id="os_intro.md_chunk_0001",
            text=TEST_DOC_2,
            source="os_intro.md",
            chunk_index=1,
            doc_sha256="abc1234567890abcdef",
        ),
        Chunk(
            id="memory.md_chunk_0000",
            text=TEST_DOC_3,
            source="memory.md",
            chunk_index=0,
            doc_sha256="def9876543210fedcba",
        ),
        Chunk(
            id="memory.md_chunk_0001",
            text=TEST_DOC_4,
            source="memory.md",
            chunk_index=1,
            doc_sha256="def9876543210fedcba",
        ),
    ]
    vectors = emb.embed_documents([c.text for c in chunks])
    store.upsert(chunks, vectors)
    return store


@pytest.fixture
def fixture_engine(tmp_path: Path, fixture_store: NumpyStore) -> DocuMind:
    """Create a DocuMind engine wired to fixture_store and CorpusEmbedder."""
    settings = Settings(home=tmp_path, min_score=0.35)
    emb = CorpusEmbedder()
    return DocuMind(settings, emb, fixture_store, llm=None)


@pytest.fixture
def mcp_server(tmp_path: Path, fixture_engine: DocuMind):
    """Create a FastMCP server configured with the test fixture engine."""
    return create_mcp_server(home=tmp_path, engine=fixture_engine)


def pytest_pyfunc_call(pyfuncitem):
    """Run async test functions automatically using asyncio."""
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(pyfuncitem.obj):
        testfunction = pyfuncitem.obj
        funcargs = pyfuncitem.funcargs
        testargs = {arg: funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(testfunction(**testargs))
        return True
    return None
