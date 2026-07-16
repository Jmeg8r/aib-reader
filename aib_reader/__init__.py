"""aib-reader — self-owned RSS aggregation substrate for the ASTGL ecosystem.

Library first. Import the public contract directly (no MCP, no server):

    from aib_reader import fetch_recent_items, mark_processed, Item

The MCP server (``aib_reader.mcp_server``) is a thin wrapper for interactive use
and is intentionally NOT imported here, so importing the library never drags in
the ``mcp`` SDK. See README.md for the full contract.
"""

from __future__ import annotations

from aib_reader.api import (
    PollSummary,
    add_feed,
    fetch_recent_items,
    list_feeds,
    mark_processed,
    poll_feeds,
    remove_feed,
    search_items,
)
from aib_reader.models import Feed, Item, RecentItemsQuery

__version__ = "0.0.1"

__all__ = [
    "__version__",
    # contract functions
    "fetch_recent_items",
    "mark_processed",
    "search_items",
    "list_feeds",
    "add_feed",
    "remove_feed",
    "poll_feeds",
    # contract types
    "Item",
    "Feed",
    "RecentItemsQuery",
    "PollSummary",
]
