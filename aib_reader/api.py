"""Public library API — the integration contract.

Every MCP tool maps 1:1 to a function here. The query functions are read-only over
the local store (fast, deterministic, no network); the network refresh is the
separate, side-effecting ``poll_feeds()``. A consumer like aib-pipeline typically
calls ``poll_feeds()`` (or relies on a scheduled poll) and then queries.

This module must NEVER import the ``mcp`` SDK — ``mcp_server.py`` imports this,
never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass

from aib_reader._logging import get_logger
from aib_reader.config import Config, load_config
from aib_reader.models import Feed, Item
from aib_reader.store.sqlite import SqliteStore

log = get_logger(__name__)


@dataclass
class PollSummary:
    """Result of a network poll across feeds."""

    feeds_polled: int
    feeds_failed: int
    new_items: int


def _store(config: Config | None = None) -> SqliteStore:
    """Build and initialize the configured store."""
    cfg = config or load_config()
    store = SqliteStore(cfg.db_path)
    store.init_schema()
    return store


def poll_feeds(categories: list[str] | None = None) -> PollSummary:
    """Network refresh: fetch all active feeds (optionally filtered to categories),
    dedup, and store new items. Side-effecting. (Real impl: v0.0b.)
    """
    raise NotImplementedError("poll_feeds: implemented in v0.0b (see tasks/todo.md)")


def fetch_recent_items(
    since: str = "24h",
    limit: int = 100,
    category: str | None = None,
) -> list[Item]:
    """Return newest-first, dedupped recent items from the local store.

    Read-only (no network). ``since`` accepts a duration suffix (``"24h"`` /
    ``"7d"`` / ``"2w"``) or an ISO-8601 timestamp; invalid input raises
    ``ValueError``. ``category`` is an exact match when provided.
    """
    from aib_reader._time import parse_since  # local import keeps module load light

    cutoff = parse_since(since)
    log.debug("fetch_recent_items since=%s (cutoff=%s) limit=%s category=%s", since, cutoff, limit, category)
    return _store().recent_items(since=cutoff, limit=limit, category=category)


def search_items(query: str, limit: int = 50) -> list[Item]:
    """Keyword search across stored items (newest-first), deduped to survivors."""
    log.debug("search_items query=%r limit=%s", query, limit)
    return _store().search_items(query=query, limit=limit)


def mark_processed(item_ids: list[str], consumer: str = "default") -> int:
    """Record a consumer-scoped processed cursor for the given item ids.

    Consumer-scoped: marking processed for ``consumer="aib-pipeline"`` does NOT
    hide the items from a different consumer. Pass YOUR consumer name. Returns the
    number of cursor rows written.
    """
    if not consumer:
        raise ValueError("`consumer` must be a non-empty identifier")
    log.debug("mark_processed n=%s consumer=%s", len(item_ids), consumer)
    return _store().mark_processed(item_ids=item_ids, consumer=consumer)


def list_feeds() -> list[Feed]:
    """Return all configured feeds (URL, categories, last-fetch time, active)."""
    return _store().list_feeds()


def add_feed(url: str, category: str | None = None) -> Feed:
    """Add a feed to the canonical ``config/feeds.yaml`` and upsert it into the
    store. (Real impl: v0.0b.)"""
    raise NotImplementedError("add_feed: implemented in v0.0b (see tasks/todo.md)")
