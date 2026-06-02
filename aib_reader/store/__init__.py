"""Storage backend abstraction.

The ``Store`` Protocol is the swappable seam: SQLite is the v1 backend, but a
Miniflux/FreshRSS-backed implementation could satisfy the same interface later
WITHOUT changing the public library API. Keep this interface clean.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from aib_reader.models import Feed, Item


@runtime_checkable
class Store(Protocol):
    """Persistence contract. Implementations own items + processed cursors;
    the feed list itself is canonical in config/feeds.yaml and upserted here."""

    def init_schema(self) -> None:
        """Create tables/indexes if absent. Idempotent."""
        ...

    def upsert_feeds(self, feeds: list[Feed]) -> None:
        """Reconcile the canonical feed list (from feeds.yaml) into the store."""
        ...

    def list_feeds(self) -> list[Feed]:
        ...

    def add_item(self, item: Item) -> str:
        """Insert an item (post-dedup). Returns the stable surrogate id."""
        ...

    def recent_items(
        self,
        *,
        since: datetime,
        limit: int,
        category: str | None = None,
    ) -> list[Item]:
        """Newest-first, deduped (survivors only), filtered by time + category."""
        ...

    def search_items(self, query: str, limit: int) -> list[Item]:
        ...

    def mark_processed(self, item_ids: list[str], consumer: str) -> int:
        """Record consumer-scoped processed cursors. Returns rows written."""
        ...

    def deactivate_feed(self, feed_id: str) -> None:
        ...
