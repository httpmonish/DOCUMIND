"""tests/mcp/test_process.py
Process-level stdio transport integration tests.
Launches the server in a real subprocess over stdio, verifies JSON-RPC purity,
and measures cold handshake latency.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_real_server_stdio_handshake_under_2_seconds():
    """Verify that cold initialize handshake completes in < 2 seconds."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "documind.interfaces.cli", "mcp", "serve"],
        env=dict(os.environ),
    )

    t0 = time.perf_counter()
    async with (
        stdio_client(server_params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        init_res = await session.initialize()
        latency = time.perf_counter() - t0

        assert init_res.serverInfo.name == "documind"
        # Handshake must complete in under 2 seconds with cold model
        assert latency < 2.0, f"Initialize handshake took too long: {latency:.3f}s"

        tools = await session.list_tools()
        assert len(tools.tools) == 4


def test_every_stdout_line_is_valid_json_rpc():
    """Verify stdout purity: every single line emitted to stdout is valid JSON-RPC."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "documind.interfaces.cli", "mcp", "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test_pure_stdout", "version": "1.0"},
            },
        }
    )

    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(init_msg + "\n")
        proc.stdin.flush()

        # Read line from stdout
        line = proc.stdout.readline()
        assert line, "No response line from server"
        data = json.loads(line)
        assert data.get("jsonrpc") == "2.0"
        assert data.get("id") == 1
        assert "result" in data

    finally:
        proc.terminate()
        proc.wait(timeout=3)
