"""End-to-end poll_feeds tests over a mocked network (httpx.MockTransport).

Exercises the real api.poll_feeds path: upsert -> fetch -> flood-cap -> dedup ->
store -> record health. No real requests are made."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import aib_reader.api as api_mod
from aib_reader.api import _flood_cap, poll_feeds
from aib_reader.fetcher import HttpxFetcher
from aib_reader.models import Item

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"
NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _route(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    if host == "clean.example.com":
        return httpx.Response(200, content=(FIXTURES / "clean.xml").read_bytes())
    if host == "hype.example.com":
        return httpx.Response(200, content=(FIXTURES / "dup_story.xml").read_bytes())
    if host == "dead.example.com":
        return httpx.Response(404)
    return httpx.Response(500)


@pytest.fixture
def patched(tmp_path, monkeypatch):
    """Isolate config + force the fetcher to use a MockTransport."""
    monkeypatch.setenv("AIB_READER_DB_PATH", str(tmp_path / "store.db"))
    feeds_yaml = tmp_path / "feeds.yaml"
    feeds_yaml.write_text(
        "feeds:\n"
        "  - url: https://clean.example.com/rss\n"
        "    title: Clean\n"
        "    categories: [AI World]\n"
        "  - url: https://dead.example.com/rss\n"
        "    title: Dead\n"
        "    categories: [AI World]\n"
        "  - url: https://hype.example.com/rss\n"
        "    title: Hype\n"
        "    categories: [AI World]\n"
    )
    monkeypatch.setenv("AIB_READER_FEEDS_CONFIG", str(feeds_yaml))

    class _MockFetcher(HttpxFetcher):
        def __init__(self, **kw):
            kw.pop("transport", None)
            super().__init__(transport=httpx.MockTransport(_route), **kw)

    monkeypatch.setattr(api_mod, "HttpxFetcher", _MockFetcher)
    return tmp_path


def test_poll_feeds_end_to_end(patched):
    summary = poll_feeds(categories=["AI World"])
    # clean (2 items) + hype (1 fuzzy-dup of clean) ; dead 404s.
    assert summary.feeds_polled == 2
    assert summary.feeds_failed == 1
    # The hype item is a same-story duplicate, so it is NOT a new survivor.
    assert summary.new_items == 2


def test_poll_feeds_dedups_cross_feed_story(patched):
    poll_feeds(categories=["AI World"])
    from aib_reader import fetch_recent_items

    items = fetch_recent_items(since="7d", category="AI World")
    claude_stories = [it for it in items if "Claude 5" in (it.title or "")]
    # Both feeds carried the Claude 5 story; only the survivor remains.
    assert len(claude_stories) == 1


def test_poll_feeds_records_dead_feed_health(patched):
    poll_feeds(categories=["AI World"])
    from aib_reader.api import _store

    health = {h["title"]: h for h in _store().feed_health()}
    assert health["Dead"]["consecutive_failures"] == 1
    assert health["Dead"]["last_status"] == 404
    assert health["Clean"]["consecutive_failures"] == 0


def test_mark_processed_covers_survivor(patched):
    poll_feeds(categories=["AI World"])
    from aib_reader import fetch_recent_items, mark_processed

    items = fetch_recent_items(since="7d", category="AI World")
    n = mark_processed([it.id for it in items], consumer="aib-pipeline")
    assert n == len(items)


# --- flood cap (pure unit) -------------------------------------------------


def _it(title, published):
    return Item(id=title, feed_id="f1", title=title, published_at=published, fetched_at=NOW)


def test_flood_cap_drops_old_on_first_fetch():
    items = [
        _it("fresh", NOW - timedelta(days=2)),
        _it("ancient", NOW - timedelta(days=400)),
        _it("undated", None),  # kept: coalesces to fetched_at
    ]
    capped = _flood_cap(items, is_first_fetch=True, horizon_days=14)
    titles = {it.title for it in capped}
    assert titles == {"fresh", "undated"}


def test_flood_cap_noop_after_first_fetch():
    items = [_it("ancient", NOW - timedelta(days=400))]
    assert _flood_cap(items, is_first_fetch=False, horizon_days=14) == items
