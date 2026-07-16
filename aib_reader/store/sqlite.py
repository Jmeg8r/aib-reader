"""SQLite backend (the v1 ``Store`` implementation).

The schema is real (created on ``init_schema``) and all query/write methods are
implemented in v0.0b. Two load-bearing design decisions live directly in the
tables: consumer-scoped cursors (``processed_items``) and the dedup survivor
pointer (``items.canonical_item_id``).

A row in ``items`` is a *survivor* iff ``canonical_item_id IS NULL OR
canonical_item_id = id``. Duplicates point ``canonical_item_id`` at their
survivor and are excluded from every query, so consumers only ever see (and
``mark_processed``) survivor ids.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from aib_reader._logging import get_logger
from aib_reader._time import now_utc, to_utc
from aib_reader.models import Feed, Item

log = get_logger(__name__)

# WHAT: the v1 schema. WHY: consumer-scoped cursors (processed_items) + dedup
# survivor pointer (items.canonical_item_id) are the two load-bearing design
# decisions, expressed directly in the tables. The feeds table also carries
# per-fetch health (last_status / consecutive_failures / last_error) so `doctor`
# can report and deactivate dead feeds.
SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS feeds (
    id                   TEXT PRIMARY KEY,
    url                  TEXT NOT NULL UNIQUE,
    title                TEXT,
    site_url             TEXT,
    active               INTEGER NOT NULL DEFAULT 1,
    last_fetched_at      TEXT,
    etag                 TEXT,
    modified             TEXT,
    last_status          INTEGER,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error           TEXT,
    created_at           TEXT NOT NULL
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
    id                TEXT PRIMARY KEY,           -- stable surrogate (survivor key)
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
CREATE INDEX IF NOT EXISTS idx_items_feed_published ON items(feed_id, published_at);
CREATE INDEX IF NOT EXISTS idx_processed_consumer_item ON processed_items(consumer, item_id);
"""

# WHAT: columns added after the initial scaffold schema. WHY: dev DBs created by
# earlier `doctor` runs predate these; ALTER them in idempotently so we never
# silently break on an existing store.
_FEEDS_ADDED_COLUMNS = {
    "last_status": "INTEGER",
    "consecutive_failures": "INTEGER NOT NULL DEFAULT 0",
    "last_error": "TEXT",
}

# A row is a survivor (not a fuzzy duplicate) when this predicate holds.
_SURVIVOR_PREDICATE = "(items.canonical_item_id IS NULL OR items.canonical_item_id = items.id)"


def _iso(dt: datetime | None) -> str | None:
    """Serialize a datetime to ISO-8601 UTC, or None."""
    if dt is None:
        return None
    return to_utc(dt).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return to_utc(datetime.fromisoformat(value))
    except ValueError:
        log.warning("could not parse stored datetime %r", value)
        return None


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
        self._ensure_columns(conn)
        conn.commit()
        log.debug("schema initialized")

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        """Idempotently ALTER in any columns missing from an older feeds table."""
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(feeds)").fetchall()}
        for name, decl in _FEEDS_ADDED_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE feeds ADD COLUMN {name} {decl}")
                log.info("migrated feeds: added column %s", name)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- feeds ---------------------------------------------------------------

    def upsert_feeds(self, feeds: list[Feed]) -> None:
        """Reconcile the canonical feed list (from feeds.yaml) into the store.

        Idempotent. Preserves runtime state (etag/modified/last_fetched_at/
        consecutive_failures/last_status/last_error/active) on existing rows —
        only the config-owned fields (title/site_url/categories) are refreshed.
        """
        conn = self.connect()
        now = now_utc().isoformat()
        for feed in feeds:
            conn.execute(
                """
                INSERT INTO feeds (id, url, title, site_url, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    title = excluded.title,
                    site_url = excluded.site_url
                """,
                (feed.id, feed.url, feed.title, feed.site_url, int(feed.active), now),
            )
            self._set_feed_categories(conn, feed.id, feed.categories)
        conn.commit()
        log.info("upsert_feeds: reconciled %d feeds", len(feeds))

    def _set_feed_categories(self, conn: sqlite3.Connection, feed_id: str, categories: list[str]) -> None:
        conn.execute("DELETE FROM feed_categories WHERE feed_id = ?", (feed_id,))
        for name in categories:
            conn.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
            row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO feed_categories (feed_id, category_id) VALUES (?, ?)",
                (feed_id, row["id"]),
            )

    def list_feeds(self) -> list[Feed]:
        conn = self.connect()
        rows = conn.execute("SELECT * FROM feeds ORDER BY title COLLATE NOCASE").fetchall()
        return [self._row_to_feed(conn, r) for r in rows]

    def _row_to_feed(self, conn: sqlite3.Connection, r: sqlite3.Row) -> Feed:
        cats = [
            c["name"]
            for c in conn.execute(
                """
                SELECT categories.name FROM categories
                JOIN feed_categories ON feed_categories.category_id = categories.id
                WHERE feed_categories.feed_id = ?
                ORDER BY categories.name
                """,
                (r["id"],),
            ).fetchall()
        ]
        return Feed(
            id=r["id"],
            url=r["url"],
            title=r["title"],
            site_url=r["site_url"],
            categories=cats,
            active=bool(r["active"]),
            last_fetched_at=_parse_dt(r["last_fetched_at"]),
            etag=r["etag"],
            modified=r["modified"],
        )

    def deactivate_feed(self, feed_id: str) -> None:
        conn = self.connect()
        conn.execute("UPDATE feeds SET active = 0 WHERE id = ?", (feed_id,))
        conn.commit()
        log.info("deactivated feed %s", feed_id)

    def delete_feed(self, feed_id: str) -> None:
        """Hard-delete a feed and all its items. FK ``ON DELETE CASCADE`` removes
        the feed's ``feed_categories``, ``items``, and (transitively) their
        ``processed_items`` cursor rows.

        WHY the pre-delete repoint: ``items.canonical_item_id`` (the dedup survivor
        pointer) is a bare column with NO foreign key, unlike ``feed_id``. So fuzzy
        *duplicates* living in OTHER, still-active feeds can point at a survivor
        that lives in THIS feed. Cascade-deleting this feed would drop that survivor
        and orphan those duplicates — per ``_SURVIVOR_PREDICATE`` they'd then be
        neither NULL nor self-referencing, silently vanishing from every query.

        For each orphaned cluster, elect ONE deterministic replacement survivor (the
        min id among the cluster's surviving duplicates) and repoint the whole
        cluster to it — so a story that was deduped to a single entry stays a single
        entry, instead of every duplicate becoming its own survivor (which would
        make the story reappear once per duplicate). Snapshot the mapping in Python
        first, so the repoint never reads its own partial writes.
        """
        conn = self.connect()
        # Impacted duplicates: rows in OTHER feeds whose survivor lives in this feed.
        impacted = conn.execute(
            """
            SELECT id, canonical_item_id FROM items
            WHERE feed_id != ?
              AND canonical_item_id IN (SELECT id FROM items WHERE feed_id = ?)
            """,
            (feed_id, feed_id),
        ).fetchall()
        # Group by dying survivor; elect the min-id member as the cluster's new
        # survivor and repoint every member (incl. itself) to it.
        clusters: dict[str, list[str]] = {}
        for row in impacted:
            clusters.setdefault(row["canonical_item_id"], []).append(row["id"])
        for member_ids in clusters.values():
            replacement = min(member_ids)
            conn.executemany(
                "UPDATE items SET canonical_item_id = ? WHERE id = ?",
                [(replacement, item_id) for item_id in member_ids],
            )
        conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
        conn.commit()
        log.info("delete_feed: hard-deleted feed %s (items cascade-deleted)", feed_id)

    def record_fetch_success(
        self,
        feed_id: str,
        *,
        status: int | None,
        etag: str | None,
        modified: str | None,
        fetched_at: datetime,
    ) -> None:
        conn = self.connect()
        conn.execute(
            """
            UPDATE feeds SET
                last_fetched_at = ?,
                last_status = ?,
                etag = ?,
                modified = ?,
                consecutive_failures = 0,
                last_error = NULL
            WHERE id = ?
            """,
            (_iso(fetched_at), status, etag, modified, feed_id),
        )
        conn.commit()

    def record_fetch_failure(self, feed_id: str, *, status: int | None, error: str) -> None:
        conn = self.connect()
        conn.execute(
            """
            UPDATE feeds SET
                last_status = ?,
                last_error = ?,
                consecutive_failures = consecutive_failures + 1
            WHERE id = ?
            """,
            (status, error, feed_id),
        )
        conn.commit()
        log.warning("feed %s fetch failed (status=%s): %s", feed_id, status, error)

    def feed_health(self) -> list[dict]:
        """Per-feed health for `doctor`: url, active, last_fetched_at, last_status,
        consecutive_failures, last_error, and item_count."""
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT
                feeds.id, feeds.url, feeds.title, feeds.active, feeds.last_fetched_at,
                feeds.last_status, feeds.consecutive_failures, feeds.last_error,
                (SELECT COUNT(*) FROM items WHERE items.feed_id = feeds.id) AS item_count
            FROM feeds
            ORDER BY feeds.consecutive_failures DESC, feeds.title COLLATE NOCASE
            """
        ).fetchall()
        return [dict(r) for r in rows]

    # --- items ---------------------------------------------------------------

    def add_item(self, item: Item) -> str:
        """Insert an item (post-dedup). Returns the stable surrogate id.

        ``INSERT OR IGNORE``: if a row with this id already exists (exact dup —
        same canonical_url/guid/content), it is left untouched. The survivor
        pointer defaults to the item's own id; a fuzzy duplicate is recorded by
        passing an item whose ``id`` already encodes its own identity and then
        calling ``assign_survivor``.
        """
        conn = self.connect()
        canonical_item_id = item.id  # self-survivor by default
        conn.execute(
            """
            INSERT OR IGNORE INTO items
                (id, feed_id, guid, url, canonical_url, title, summary, author,
                 published_at, fetched_at, content_hash, canonical_item_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.id,
                item.feed_id,
                item.guid,
                item.url,
                item.canonical_url,
                item.title,
                item.summary,
                item.author,
                _iso(item.published_at),
                _iso(item.fetched_at or now_utc()),
                None,
                canonical_item_id,
            ),
        )
        conn.commit()
        return item.id

    def item_exists(self, item_id: str) -> bool:
        conn = self.connect()
        return conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is not None

    def assign_survivor(self, dup_id: str, survivor_id: str) -> None:
        """Point a fuzzy-duplicate row at its survivor, removing it from queries."""
        if dup_id == survivor_id:
            return
        conn = self.connect()
        conn.execute("UPDATE items SET canonical_item_id = ? WHERE id = ?", (survivor_id, dup_id))
        conn.commit()
        log.debug("dedup: item %s -> survivor %s", dup_id, survivor_id)

    def recent_items_for_feed_categories(
        self, categories: list[str], *, since: datetime, limit: int = 200
    ) -> list[Item]:
        """Survivor items published since ``since`` whose feed carries any of the
        given categories — the candidate pool for fuzzy same-category dedup."""
        if not categories:
            return []
        conn = self.connect()
        placeholders = ",".join("?" for _ in categories)
        rows = conn.execute(
            f"""
            SELECT DISTINCT items.* FROM items
            JOIN feed_categories ON feed_categories.feed_id = items.feed_id
            JOIN categories ON categories.id = feed_categories.category_id
            WHERE categories.name IN ({placeholders})
              AND {_SURVIVOR_PREDICATE}
              AND COALESCE(items.published_at, items.fetched_at) >= ?
            ORDER BY COALESCE(items.published_at, items.fetched_at) DESC
            LIMIT ?
            """,
            (*categories, _iso(since), limit),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def recent_items(self, *, since: datetime, limit: int, category: str | None = None) -> list[Item]:
        conn = self.connect()
        params: list = [_iso(since)]
        if category:
            sql = f"""
                SELECT DISTINCT items.* FROM items
                JOIN feed_categories ON feed_categories.feed_id = items.feed_id
                JOIN categories ON categories.id = feed_categories.category_id
                WHERE {_SURVIVOR_PREDICATE}
                  AND COALESCE(items.published_at, items.fetched_at) >= ?
                  AND categories.name = ?
                ORDER BY COALESCE(items.published_at, items.fetched_at) DESC
                LIMIT ?
            """
            params.append(category)
        else:
            sql = f"""
                SELECT items.* FROM items
                WHERE {_SURVIVOR_PREDICATE}
                  AND COALESCE(items.published_at, items.fetched_at) >= ?
                ORDER BY COALESCE(items.published_at, items.fetched_at) DESC
                LIMIT ?
            """
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search_items(self, query: str, limit: int) -> list[Item]:
        conn = self.connect()
        like = f"%{query}%"
        rows = conn.execute(
            f"""
            SELECT items.* FROM items
            WHERE {_SURVIVOR_PREDICATE}
              AND (items.title LIKE ? OR items.summary LIKE ?)
            ORDER BY COALESCE(items.published_at, items.fetched_at) DESC
            LIMIT ?
            """,
            (like, like, limit),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def _row_to_item(self, r: sqlite3.Row) -> Item:
        feed_title = None
        conn = self.connect()
        frow = conn.execute("SELECT title FROM feeds WHERE id = ?", (r["feed_id"],)).fetchone()
        if frow:
            feed_title = frow["title"]
        cats = [
            c["name"]
            for c in conn.execute(
                """
                SELECT categories.name FROM categories
                JOIN feed_categories ON feed_categories.category_id = categories.id
                WHERE feed_categories.feed_id = ?
                ORDER BY categories.name
                """,
                (r["feed_id"],),
            ).fetchall()
        ]
        return Item(
            id=r["id"],
            feed_id=r["feed_id"],
            feed_title=feed_title,
            url=r["url"],
            canonical_url=r["canonical_url"],
            title=r["title"],
            summary=r["summary"],
            author=r["author"],
            guid=r["guid"],
            published_at=_parse_dt(r["published_at"]),
            fetched_at=_parse_dt(r["fetched_at"]),
            categories=cats,
        )

    # --- processed cursors ---------------------------------------------------

    def mark_processed(self, item_ids: list[str], consumer: str) -> int:
        """Record consumer-scoped processed cursors. Returns rows written.

        Keys on the survivor id (queries only ever return survivors), so one mark
        covers an item's whole duplicate cluster.
        """
        conn = self.connect()
        now = now_utc().isoformat()
        written = 0
        for item_id in item_ids:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_items (consumer, item_id, processed_at) VALUES (?, ?, ?)",
                (consumer, item_id, now),
            )
            written += cur.rowcount
        conn.commit()
        log.info("mark_processed: %d new cursor rows for consumer=%s", written, consumer)
        return written
