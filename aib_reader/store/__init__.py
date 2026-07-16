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

    def delete_feed(self, feed_id: str) -> None:
        """Hard-delete a feed and its items (cascades to categories + cursors)."""
        ...

    # --- fetch-loop + health support (used by api.poll_feeds and cli.doctor) ---

    def record_fetch_success(
        self,
        feed_id: str,
        *,
        status: int | None,
        etag: str | None,
        modified: str | None,
        fetched_at: datetime,
    ) -> None:
        """Record a successful poll: stamp validators + reset failure counter."""
        ...

    def record_fetch_failure(self, feed_id: str, *, status: int | None, error: str) -> None:
        """Record a failed poll: store the error and increment consecutive_failures."""
        ...

    def feed_health(self) -> list[dict]:
        """Per-feed health rows for `doctor`."""
        ...

    def assign_survivor(self, dup_id: str, survivor_id: str) -> None:
        """Point a fuzzy-duplicate item row at its survivor."""
        ...

    def recent_items_for_feed_categories(
        self, categories: list[str], *, since: datetime, limit: int = 200
    ) -> list[Item]:
        """Candidate survivor pool (same categories, recent) for fuzzy dedup."""
        ...
