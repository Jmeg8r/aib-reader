"""Tests for the SQLite store: feeds, items, dedup survivors, consumer cursors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aib_reader.dedup import content_hash, item_surrogate_id
from aib_reader.models import Feed, Item
from aib_reader.store.sqlite import SqliteStore

NOW = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "store.db")
    s.init_schema()
    yield s
    s.close()


def _item(store_id, feed_id, title, *, canonical_url=None, published=NOW, summary="body"):
    return Item(
        id=store_id,
        feed_id=feed_id,
        title=title,
        summary=summary,
        canonical_url=canonical_url,
        published_at=published,
        fetched_at=NOW,
    )


# --- feeds -----------------------------------------------------------------


def test_upsert_feeds_is_idempotent_and_joins_categories(store):
    feed = Feed(id="f1", url="https://e.com/rss", title="E", categories=["AI World", "tech"])
    store.upsert_feeds([feed])
    store.upsert_feeds([feed])  # twice — must not duplicate
    feeds = store.list_feeds()
    assert len(feeds) == 1
    assert set(feeds[0].categories) == {"AI World", "tech"}


def test_upsert_preserves_runtime_state(store):
    feed = Feed(id="f1", url="https://e.com/rss", title="E", categories=["AI World"])
    store.upsert_feeds([feed])
    store.record_fetch_success(
        "f1", status=200, etag='"abc"', modified="Mon, 02 Jun 2026 00:00:00 GMT", fetched_at=NOW
    )
    # Re-upsert (e.g. a later poll reloading feeds.yaml) must keep etag/last_fetched.
    store.upsert_feeds([feed])
    reloaded = store.list_feeds()[0]
    assert reloaded.etag == '"abc"'
    assert reloaded.last_fetched_at is not None


def test_record_failure_increments_then_success_resets(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss")])
    store.record_fetch_failure("f1", status=404, error="HTTP 404")
    store.record_fetch_failure("f1", status=404, error="HTTP 404")
    assert store.feed_health()[0]["consecutive_failures"] == 2
    store.record_fetch_success("f1", status=200, etag=None, modified=None, fetched_at=NOW)
    assert store.feed_health()[0]["consecutive_failures"] == 0


def test_deactivate_feed(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss")])
    store.deactivate_feed("f1")
    assert store.list_feeds()[0].active is False


def test_delete_feed_removes_feed_and_items(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss", categories=["AI World"])])
    store.add_item(_item("i1", "f1", "x"))
    store.mark_processed(["i1"], consumer="c1")
    store.delete_feed("f1")
    assert store.list_feeds() == []
    assert store.recent_items(since=NOW - timedelta(days=1), limit=50) == []
    # processed_items cascades away with the deleted item (item_id FK ON DELETE CASCADE).
    remaining = store.connect().execute("SELECT COUNT(*) AS n FROM processed_items").fetchone()["n"]
    assert remaining == 0


def test_delete_feed_repoints_cross_feed_duplicate_survivor(store):
    # Regression: a fuzzy duplicate in ANOTHER feed points at a survivor that lives
    # in the feed being deleted. Without the pre-delete repoint, the cascade drops
    # the survivor and the duplicate silently vanishes from every query.
    store.upsert_feeds([
        Feed(id="f1", url="https://a.com/rss", categories=["AI World"]),
        Feed(id="f2", url="https://b.com/rss", categories=["AI World"]),
    ])
    store.add_item(_item("surv", "f1", "Anthropic ships Claude 5", canonical_url="https://a.com/x"))
    store.add_item(_item("dup", "f2", "Anthropic ships Claude 5 today", canonical_url="https://b.com/y"))
    store.assign_survivor("dup", "surv")  # dup (in f2) -> survivor in f1
    store.delete_feed("f1")
    recent = store.recent_items(since=NOW - timedelta(days=1), limit=50)
    assert [it.id for it in recent] == ["dup"]  # promoted to its own survivor, still visible


# --- items + queries -------------------------------------------------------


def test_add_item_and_recent_items_time_filter(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss", categories=["AI World"])])
    store.add_item(_item("i_new", "f1", "Fresh", published=NOW))
    store.add_item(_item("i_old", "f1", "Stale", published=NOW - timedelta(days=10)))
    recent = store.recent_items(since=NOW - timedelta(days=1), limit=50)
    titles = {it.title for it in recent}
    assert "Fresh" in titles and "Stale" not in titles


def test_recent_items_category_filter(store):
    store.upsert_feeds([
        Feed(id="f1", url="https://a.com/rss", categories=["AI World"]),
        Feed(id="f2", url="https://b.com/rss", categories=["Politics"]),
    ])
    store.add_item(_item("a1", "f1", "AI thing"))
    store.add_item(_item("b1", "f2", "Politics thing"))
    ai = store.recent_items(since=NOW - timedelta(days=1), limit=50, category="AI World")
    assert [it.title for it in ai] == ["AI thing"]


def test_exact_duplicate_collapses_via_id(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss")])
    canon = "https://e.com/post"
    sid = item_surrogate_id(canon, None, content_hash("t", "b"))
    store.add_item(_item(sid, "f1", "t", canonical_url=canon))
    store.add_item(_item(sid, "f1", "t", canonical_url=canon))  # same id -> ignored
    assert len(store.recent_items(since=NOW - timedelta(days=1), limit=50)) == 1


def test_fuzzy_duplicate_assigned_to_survivor(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss", categories=["AI World"])])
    survivor = _item("surv", "f1", "Anthropic ships Claude 5", canonical_url="https://e.com/a")
    dup = _item("dup", "f1", "Anthropic ships Claude 5 today", canonical_url="https://e.com/b")
    store.add_item(survivor)
    store.add_item(dup)
    store.assign_survivor("dup", "surv")
    recent = store.recent_items(since=NOW - timedelta(days=1), limit=50)
    assert [it.id for it in recent] == ["surv"]  # dup excluded from queries


def test_search_items(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss")])
    store.add_item(_item("i1", "f1", "Anthropic news", summary="about Claude"))
    store.add_item(_item("i2", "f1", "Weather report", summary="sunny"))
    assert [it.title for it in store.search_items("anthropic", 10)] == ["Anthropic news"]
    assert [it.title for it in store.search_items("claude", 10)] == ["Anthropic news"]


# --- consumer-scoped cursors ----------------------------------------------


def test_mark_processed_is_consumer_scoped(store):
    store.upsert_feeds([Feed(id="f1", url="https://e.com/rss")])
    store.add_item(_item("i1", "f1", "x"))
    assert store.mark_processed(["i1"], consumer="aib-pipeline") == 1
    assert store.mark_processed(["i1"], consumer="aib-pipeline") == 0  # idempotent
    # A different consumer is unaffected — its own cursor write still counts.
    assert store.mark_processed(["i1"], consumer="updatekit") == 1
