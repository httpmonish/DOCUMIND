"""examples/mcp_demo.py
Demonstration of DocuMind Secure Read-Only MCP Server (v0.7.0).
Connects to the server over stdio using the official MCP SDK client session,
inspects registered tools, queries index metadata, and executes semantic retrieval.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def run_mcp_demo() -> None:
    print("=" * 65)
    print("  DocuMind Local MCP Server Demonstration (v0.7.0)")
    print("=" * 65)

    from pathlib import Path
    home_dir = os.environ.get("DOCUMIND_HOME") or str(Path.home() / ".documind")
    print("\n[1] Launching DocuMind stdio MCP server...")
    print(f"    Python:        {sys.executable}")
    print(f"    DOCUMIND_HOME: {home_dir}")

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
        # 1. Initialize Handshake
        init_res = await session.initialize()
        latency_ms = (time.perf_counter() - t0) * 1000
        print("\n[2] Connected to MCP Server:")
        print(f"    Server Name:    {init_res.serverInfo.name}")
        print(f"    Server Version: {init_res.serverInfo.version}")
        print(f"    Protocol:       {init_res.protocolVersion}")
        print(f"    Handshake Time: {latency_ms:.1f} ms")

        # 2. List Advertised Tools
        tools_res = await session.list_tools()
        print(f"\n[3] Discovered {len(tools_res.tools)} Read-Only Tools:")
        for t in tools_res.tools:
            hints = []
            if t.annotations:
                if t.annotations.readOnlyHint:
                    hints.append("read-only")
                if t.annotations.idempotentHint:
                    hints.append("idempotent")
            hint_str = f" ({', '.join(hints)})" if hints else ""
            print(f"    * {t.name:<18}{hint_str}")
            print(f"      Description: {t.description[:80]}...")

        # 3. Query Index Information
        print("\n[4] Querying index_info tool...")
        info_res = await session.call_tool("index_info", arguments={})
        info_data = json.loads(info_res.content[0].text)
        print(f"    Documents:   {info_data.get('document_count')}")
        print(f"    Chunks:      {info_data.get('chunk_count')}")
        print(f"    Embedder:    {info_data.get('embedder_name')}")
        print(f"    Tau Gate:    {info_data.get('tau')}")
        print(f"    Store Type:  {info_data.get('store_type')}")

        # 4. Execute Semantic Search
        query = "DocuMind architecture and retrieval pipeline"
        print("\n[5] Executing search_documents tool...")
        print(f"    Query: '{query}'")

        t_search = time.perf_counter()
        search_res = await session.call_tool(
            "search_documents",
            arguments={"query": query, "top_k": 3},
        )
        search_ms = (time.perf_counter() - t_search) * 1000
        search_data = json.loads(search_res.content[0].text)

        print(f"    Outcome:     {search_data.get('outcome')}")
        print(f"    Search Time: {search_ms:.1f} ms")
        print(f"    Top Score:   {search_data.get('top_score')}")
        print(f"    Threshold:   {search_data.get('threshold')}")
        print(f"    Notice:      {search_data.get('notice')}")

        results = search_data.get("results", [])
        print(f"\n[6] Retrieved {len(results)} Evidence Passages:")
        if not results:
            print("    (No relevant results or empty index - model will safely abstain)")
        for r in results:
            label = r["citation_label"]
            score_str = f"Score: {r['score']:.4f}, Rank: {r['rank']}"
            print(f"\n    [{label}] {r['source']} ({score_str})")
            snippet = r["text"].replace("\n", " ").strip()
            if len(snippet) > 140:
                snippet = snippet[:140] + "..."
            print(f'        "{snippet}"')

    print("\n" + "=" * 65)
    print("  Demo completed successfully. Server stdout remained 100% pure JSON-RPC.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_mcp_demo())
