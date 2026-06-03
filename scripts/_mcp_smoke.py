"""Stdio smoke test for the aib-reader MCP server.

Spawns the server exactly as Claude Code would (the absolute venv console script +
the AIB_READER_FEEDS_CONFIG env override), performs the MCP initialize handshake,
lists tools, and calls the two read tools against the real local store. Proves the
registration → launch → delegation path end to end without restarting the app.

Run:  uv run python scripts/_mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT = "/Users/jamescruce/Projects/aib-reader"
COMMAND = f"{PROJECT}/.venv/bin/aib-reader-mcp"
FEEDS = f"{PROJECT}/config/feeds.yaml"

EXPECTED = {"list_feeds", "recent_items", "search_items", "mark_processed", "add_feed"}


def _items(result) -> list:
    """Best-effort extraction of the tool's list return from a CallToolResult."""
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        # FastMCP wraps a list return as {"result": [...]}.
        for v in sc.values():
            if isinstance(v, list):
                return v
    # Fallback: parse the first text content block as JSON.
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                data = json.loads(text)
                return data if isinstance(data, list) else [data]
            except json.JSONDecodeError:
                pass
    return []


async def main() -> int:
    params = StdioServerParameters(
        command=COMMAND,
        args=[],
        # Mirror the registration env; inherit HOME/PATH so ~/.aib-reader resolves.
        env={**os.environ, "AIB_READER_FEEDS_CONFIG": FEEDS},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {t.name for t in (await session.list_tools()).tools}
            print(f"tools ({len(tools)}): {sorted(tools)}")
            assert tools == EXPECTED, f"tool mismatch: {tools ^ EXPECTED}"

            recent = _items(await session.call_tool(
                "recent_items", {"category": "AI World", "since": "7d", "limit": 5}
            ))
            print(f"recent_items(AI World, 7d): {len(recent)} items")
            for it in recent[:3]:
                print("   -", (it.get('title') or '')[:68])

            found = _items(await session.call_tool(
                "search_items", {"query": "Anthropic", "limit": 5}
            ))
            print(f"search_items('Anthropic'): {len(found)} items")
            for it in found[:3]:
                print("   -", (it.get('title') or '')[:68])

    ok = bool(recent) or bool(found)
    print("\nSMOKE:", "PASS" if ok else "FAIL (no items — try `aib-reader fetch` first)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
