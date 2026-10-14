"""tests/mcp/test_protocol.py
Protocol compliance tests for DocuMind MCP server using in-memory ClientSession.
"""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.mark.asyncio
async def test_tools_listed_and_annotated_read_only(mcp_server):
    """Assert all four tools are listed with schemas and read-only annotations."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        init_res = await session.initialize()
        assert init_res.serverInfo.name == "documind"

        tools_res = await session.list_tools()
        tools_by_name = {t.name: t for t in tools_res.tools}

        expected_tools = {
            "search_documents",
            "get_chunk",
            "list_documents",
            "index_info",
        }
        assert set(tools_by_name.keys()) == expected_tools

        for name, tool in tools_by_name.items():
            # Verify input and output schemas exist
            assert tool.inputSchema is not None, f"Tool '{name}' missing inputSchema"
            assert tool.description, f"Tool '{name}' missing description"

            # Verify security annotations
            annotations = tool.annotations
            assert annotations is not None, f"Tool '{name}' missing annotations"
            assert annotations.readOnlyHint is True, f"Tool '{name}' readOnlyHint must be True"
            assert (
                annotations.destructiveHint is False
            ), f"Tool '{name}' destructiveHint must be False"
            assert (
                annotations.idempotentHint is True
            ), f"Tool '{name}' idempotentHint must be True"
            assert (
                annotations.openWorldHint is False
            ), f"Tool '{name}' openWorldHint must be False"


@pytest.mark.asyncio
async def test_resources_and_prompts_listed(mcp_server):
    """Assert resources and prompts are correctly advertised by the server."""
    async with create_connected_server_and_client_session(mcp_server._mcp_server) as session:
        await session.initialize()

        resources_res = await session.list_resources()
        resource_uris = {str(r.uri) for r in resources_res.resources}
        assert "documind://index/info" in resource_uris

        prompts_res = await session.list_prompts()
        prompt_names = {p.name for p in prompts_res.prompts}
        assert "answer_from_documents" in prompt_names
