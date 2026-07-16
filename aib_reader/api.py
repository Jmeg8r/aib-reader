"""Public library API — the integration contract.

Every MCP tool maps 1:1 to a function here. The query functions are read-only over
the local store (fast, deterministic, no network); the network refresh is the
separate, side-effecting ``poll_feeds()``. A consumer like aib-pipeline typically
calls ``poll_feeds()`` (or relies on a scheduled poll) and then queries.

This module must NEVER import the ``mcp`` SDK — ``mcp_server.py`` imports this,
never the reverse.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from aib_reader._logging import get_logger
from aib_reader._time import now_utc
from aib_reader.config import Config, load_config
from aib_reader.dedup import is_same_story
from aib_reader.fetcher import FetchResult, HttpxFetcher
from aib_reader.models import Feed, Item
from aib_reader.store.sqlite import SqliteStore

log = get_logger(__name__)

# WHAT: how far back fuzzy "same story" dedup looks. WHY: fuzzy match is
# exact-duplicate suppression within a short window, NOT topic clustering.
_FUZZY_WINDOW_DAYS = 3


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


def _feed_matches(feed: Feed, categories: list[str] | None) -> bool:
    return categories is None or any(c in categories for c in feed.categories)


def _flood_cap(items: list[Item], *, is_first_fetch: bool, horizon_days: int) -> list[Item]:
    """On a feed's first poll, drop items older than the horizon so we don't
    ingest a flood of historical entries. Items with no published date are kept
    (they coalesce to fetched_at = now)."""
    if not is_first_fetch:
        return items
    cutoff = now_utc() - timedelta(days=horizon_days)
    capped = [it for it in items if it.published_at is None or it.published_at >= cutoff]
    dropped = len(items) - len(capped)
    if dropped:
        log.info("first-fetch flood cap: dropped %d items older than %dd", dropped, horizon_days)
    return capped


def _store_with_dedup(store: SqliteStore, feed: Feed, items: list[Item]) -> int:
    """Insert items, applying exact (id-collision) and fuzzy (same-story) dedup.
    Returns the count of genuinely new survivor rows."""
    new_count = 0
    since = now_utc() - timedelta(days=_FUZZY_WINDOW_DAYS)
    # Candidate survivors in the same categories for fuzzy comparison.
    candidates = store.recent_items_for_feed_categories(feed.categories, since=since)
    for item in items:
        if store.item_exists(item.id):
            continue  # exact duplicate (same canonical_url/guid/content)
        # Fuzzy: same story under a different URL within the window + categories.
        survivor = next((c for c in candidates if is_same_story(item.title, c.title)), None)
        store.add_item(item)
        if survivor is not None:
            store.assign_survivor(item.id, survivor.id)
        else:
            new_count += 1
            candidates.append(item)  # so later items in this batch dedup against it
    return new_count


def poll_feeds(categories: list[str] | None = None) -> PollSummary:
    """Network refresh: fetch all active feeds (optionally filtered to categories),
    dedup, and store new items. Side-effecting.

    Synchronous facade: the async fetcher runs under ``asyncio.run`` here so the
    library's public surface stays sync (the 4am cron calls this directly).
    """
    cfg = load_config()
    store = _store(cfg)

    from aib_reader.opml import load_feeds_yaml

    if not cfg.feeds_config.exists():
        log.warning("poll_feeds: feeds config %s not found — nothing to poll", cfg.feeds_config)
        return PollSummary(feeds_polled=0, feeds_failed=0, new_items=0)

    feeds_yaml = load_feeds_yaml(cfg.feeds_config)
    store.upsert_feeds(feeds_yaml)

    active = [f for f in store.list_feeds() if f.active and _feed_matches(f, categories)]
    log.info("poll_feeds: %d active feeds match (categories=%s)", len(active), categories)
    if not active:
        return PollSummary(feeds_polled=0, feeds_failed=0, new_items=0)

    fetcher = HttpxFetcher(
        user_agent=cfg.user_agent,
        timeout=cfg.fetch_timeout,
        concurrency=cfg.fetch_concurrency,
    )
    results: list[FetchResult] = asyncio.run(fetcher.fetch_many(active))
    by_id = {f.id: f for f in active}

    polled = failed = new_items = 0
    for result in results:
        feed = by_id[result.feed_id]
        if not result.ok:
            failed += 1
            store.record_fetch_failure(feed.id, status=result.status, error=result.error or "unknown")
            continue

        polled += 1
        if not result.not_modified:
            is_first = feed.last_fetched_at is None
            items = _flood_cap(result.items, is_first_fetch=is_first, horizon_days=cfg.first_fetch_horizon_days)
            new_items += _store_with_dedup(store, feed, items)
        store.record_fetch_success(
            feed.id,
            status=result.status,
            etag=result.etag,
            modified=result.modified,
            fetched_at=now_utc(),
        )

    log.info("poll_feeds done: polled=%d failed=%d new_items=%d", polled, failed, new_items)
    return PollSummary(feeds_polled=polled, feeds_failed=failed, new_items=new_items)


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
    store. ``feeds.yaml`` is canonical; the DB is reconciled from it.

    Idempotent: re-adding an existing feed (matched by canonical URL) merges the
    new category rather than duplicating the entry.
    """
    if not url or not url.strip():
        raise ValueError("`url` must be a non-empty feed URL")
    url = url.strip()

    from aib_reader.dedup import canonical_url, feed_id
    from aib_reader.opml import load_feeds_yaml, write_feeds_yaml

    cfg = load_config()
    feeds = load_feeds_yaml(cfg.feeds_config) if cfg.feeds_config.exists() else []

    target_canon = canonical_url(url)
    existing = next((f for f in feeds if canonical_url(f.url) == target_canon), None)
    if existing is not None:
        if category and category not in existing.categories:
            existing.categories.append(category)
        result_feed = existing
    else:
        result_feed = Feed(
            id=feed_id(url),
            url=url,
            categories=[category] if category else [],
        )
        feeds.append(result_feed)

    write_feeds_yaml(feeds, cfg.feeds_config, source="add_feed")
    store = _store(cfg)
    store.upsert_feeds([result_feed])
    log.info("add_feed: %s (category=%s)", url, category)
    return result_feed


def remove_feed(url: str) -> bool:
    """Remove a feed from the canonical ``config/feeds.yaml`` and hard-delete it
    (and its items) from the store. Matched by canonical URL, exactly like
    ``add_feed`` — the inverse operation.

    Idempotent: removing a URL with no matching feed is a no-op that returns
    ``False`` (not an error). Returns ``True`` when a feed was found and removed.
    """
    if not url or not url.strip():
        raise ValueError("`url` must be a non-empty feed URL")
    url = url.strip()

    from aib_reader.dedup import canonical_url
    from aib_reader.opml import load_feeds_yaml, write_feeds_yaml

    cfg = load_config()
    feeds = load_feeds_yaml(cfg.feeds_config) if cfg.feeds_config.exists() else []

    target_canon = canonical_url(url)
    match = next((f for f in feeds if canonical_url(f.url) == target_canon), None)
    if match is None:
        log.info("remove_feed: no feed matches %s — no-op", url)
        return False

    remaining = [f for f in feeds if f.id != match.id]
    write_feeds_yaml(remaining, cfg.feeds_config, source="remove_feed")
    store = _store(cfg)
    store.delete_feed(match.id)
    log.info("remove_feed: removed %s (id=%s)", url, match.id)
    return True
