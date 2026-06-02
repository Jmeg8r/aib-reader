"""SQLite backend (the v1 ``Store`` implementation).

The schema is real (created on ``init_schema``); the query/write methods are
stubbed for v0.0b. Connection management and DDL land now so the rest of the
package can target a concrete store.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from aib_reader._logging import get_logger
from aib_reader.models import Feed, Item

log = get_logger(__name__)

# WHAT: the v1 schema. WHY: consumer-scoped cursors (processed_items) + dedup
# survivor pointer (items.canonical_item_id) are the two load-bearing design
# decisions, expressed directly in the tables.
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS feeds (
    id              TEXT PRIMARY KEY,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT,
    site_url        TEXT,
    active          INTEGER NOT NULL DEFAULT 1,
    last_fetched_at TEXT,
    etag            TEXT,
    modified        TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS feed_categories (
    feed_id     TEXT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (feed_id, category_id)
);

CREATE TABLE IF NOT EXISTS items (
    id                TEXT PRIMARY KEY,           -- stable surrogate (survivor)
    feed_id           TEXT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid              TEXT,
    url               TEXT,
    canonical_url     TEXT,
    title             TEXT,
    summary           TEXT,
    author            TEXT,
    published_at      TEXT,                       -- ISO-8601 UTC
    fetched_at        TEXT NOT NULL,              -- ISO-8601 UTC
    content_hash      TEXT,
    canonical_item_id TEXT                         -- points at the dedup survivor
);

CREATE TABLE IF NOT EXISTS processed_items (
    consumer     TEXT NOT NULL,                   -- consumer-scoped cursor
    item_id      TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (consumer, item_id)
);

CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_canonical_url ON items(canonical_url);
CREATE INDEX IF NOT EXISTS idx_items_feed_guid ON items(feed_id, guid);
CREATE INDEX IF NOT EXISTS idx_items_canonical_item_id ON items(canonical_item_id);
CREATE INDEX IF NOT EXISTS idx_processed_consumer_item ON processed_items(consumer, item_id);
"""

_NOT_YET = "implemented in v0.0b (see tasks/todo.md)"


class SqliteStore:
    """A local SQLite-backed ``Store``. Satisfies the ``Store`` Protocol."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open (once) the SQLite connection, creating the parent dir."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._conn = conn
            log.debug("opened sqlite store at %s", self.db_path)
        return self._conn

    def init_schema(self) -> None:
        conn = self.connect()
        conn.executescript(SCHEMA_DDL)
        conn.commit()
        log.debug("schema initialized")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- v0.0b query/write surface (stubbed) ---------------------------------

    def upsert_feeds(self, feeds: list[Feed]) -> None:
        raise NotImplementedError(f"SqliteStore.upsert_feeds: {_NOT_YET}")

    def list_feeds(self) -> list[Feed]:
        raise NotImplementedError(f"SqliteStore.list_feeds: {_NOT_YET}")

    def add_item(self, item: Item) -> str:
        raise NotImplementedError(f"SqliteStore.add_item: {_NOT_YET}")

    def recent_items(self, *, since: datetime, limit: int, category: str | None = None) -> list[Item]:
        raise NotImplementedError(f"SqliteStore.recent_items: {_NOT_YET}")

    def search_items(self, query: str, limit: int) -> list[Item]:
        raise NotImplementedError(f"SqliteStore.search_items: {_NOT_YET}")

    def mark_processed(self, item_ids: list[str], consumer: str) -> int:
        raise NotImplementedError(f"SqliteStore.mark_processed: {_NOT_YET}")

    def deactivate_feed(self, feed_id: str) -> None:
        raise NotImplementedError(f"SqliteStore.deactivate_feed: {_NOT_YET}")
