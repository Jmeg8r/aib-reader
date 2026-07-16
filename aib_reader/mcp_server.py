"""Local-stdio MCP server — thin wrapper over the library.

Each tool maps 1:1 to a function in ``aib_reader.api`` and simply delegates to it.
This module imports the ``mcp`` SDK; the library (``aib_reader.api``) does NOT
import this module, so ``from aib_reader import ...`` stays MCP-free and the
aib-pipeline cron pays zero MCP transport overhead.

Register user-scope in ~/.claude.json:
    {"mcpServers": {"aib-reader": {"type": "stdio", "command": "aib-reader-mcp",
                                    "args": [], "env": {}}}}
"""

from __future__ import annotations

import dataclasses

from mcp.server.fastmcp import FastMCP

from aib_reader import api
from aib_reader._logging import get_logger

log = get_logger(__name__)

mcp = FastMCP("aib-reader")


@mcp.tool()
def list_feeds() -> list[dict]:
    """Return all configured feeds (URL, categories, last-fetch time, active)."""
    log.info("mcp:list_feeds")
    return [f.model_dump(mode="json") for f in api.list_feeds()]


@mcp.tool()
def recent_items(limit: int = 100, since: str = "24h", category: str | None = None) -> list[dict]:
    """Newest-first, dedupped recent items. ``since`` = '24h'/'7d'/'2w' or ISO-8601."""
    log.info("mcp:recent_items since=%s limit=%s category=%s", since, limit, category)
    return [i.model_dump(mode="json") for i in api.fetch_recent_items(since=since, limit=limit, category=category)]


@mcp.tool()
def search_items(query: str, limit: int = 50) -> list[dict]:
    """Keyword search across stored items."""
    log.info("mcp:search_items query=%r limit=%s", query, limit)
    return [i.model_dump(mode="json") for i in api.search_items(query, limit=limit)]


@mcp.tool()
def mark_processed(item_ids: list[str], consumer: str) -> int:
    """Record a consumer-scoped processed cursor. Returns rows written."""
    log.info("mcp:mark_processed n=%s consumer=%s", len(item_ids), consumer)
    return api.mark_processed(item_ids, consumer=consumer)


@mcp.tool()
def add_feed(url: str, category: str | None = None) -> dict:
    """Add a feed to config/feeds.yaml and the store."""
    log.info("mcp:add_feed url=%s category=%s", url, category)
    return api.add_feed(url, category=category).model_dump(mode="json")


@mcp.tool()
def remove_feed(url: str) -> bool:
    """Remove a feed from config/feeds.yaml and hard-delete it (and its items) from the store."""
    log.info("mcp:remove_feed url=%s", url)
    return api.remove_feed(url)


@mcp.tool()
def poll_feeds(categories: list[str] | None = None) -> dict:
    """Network refresh: fetch active feeds (optionally filtered to categories), dedup, store new items."""
    log.info("mcp:poll_feeds categories=%s", categories)
    return dataclasses.asdict(api.poll_feeds(categories=categories))


def main() -> None:
    """Entry point for the ``aib-reader-mcp`` console script (stdio transport)."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
