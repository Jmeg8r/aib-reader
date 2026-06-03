"""Tests for HttpxFetcher: date parsing, per-feed isolation, conditional GET.

All network is faked via httpx.MockTransport — no real requests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from aib_reader.fetcher import HttpxFetcher
from aib_reader.models import Feed

FIXTURES = Path(__file__).parent / "fixtures" / "feeds"


def _fetcher(handler) -> HttpxFetcher:
    return HttpxFetcher(
        user_agent="test/1.0",
        timeout=5.0,
        concurrency=4,
        transport=httpx.MockTransport(handler),
    )


def _serve(path: Path, *, status=200, headers=None):
    body = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers=headers or {})

    return handler


@pytest.mark.asyncio
async def test_fetch_clean_feed_parses_items_and_dates():
    fetcher = _fetcher(_serve(FIXTURES / "clean.xml"))
    result = await fetcher.fetch_feed(Feed(id="f1", url="https://clean.example.com/rss"))
    assert result.ok
    assert len(result.items) == 2
    first = result.items[0]
    assert first.title == "Anthropic ships Claude 5"
    assert first.published_at is not None and first.published_at.tzinfo is not None
    # tracking param stripped in canonical_url
    assert "utm_source" not in (first.canonical_url or "")


@pytest.mark.asyncio
async def test_undated_entries_get_null_published(caplog):
    fetcher = _fetcher(_serve(FIXTURES / "ugly_nodate.xml"))
    result = await fetcher.fetch_feed(Feed(id="f1", url="https://ugly.example.com/rss"))
    assert result.ok and len(result.items) == 2
    assert all(it.published_at is None for it in result.items)
    # The entry with no link falls back to its guid for identity.
    guid_item = next(it for it in result.items if it.url is None)
    assert guid_item.id  # still addressable


@pytest.mark.asyncio
async def test_http_error_is_isolated_not_raised():
    fetcher = _fetcher(_serve(FIXTURES / "clean.xml", status=404))
    result = await fetcher.fetch_feed(Feed(id="f1", url="https://dead.example.com/rss"))
    assert result.ok is False
    assert result.status == 404
    assert "404" in result.error


@pytest.mark.asyncio
async def test_304_not_modified():
    def handler(request: httpx.Request) -> httpx.Response:
        # conditional headers must have been sent
        assert request.headers.get("If-None-Match") == '"etag123"'
        return httpx.Response(304)

    fetcher = _fetcher(handler)
    feed = Feed(id="f1", url="https://e.com/rss", etag='"etag123"')
    result = await fetcher.fetch_feed(feed)
    assert result.ok and result.not_modified and result.status == 304
    assert result.items == []


@pytest.mark.asyncio
async def test_fetch_many_isolates_one_bad_feed():
    def handler(request: httpx.Request) -> httpx.Response:
        if "bad" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=(FIXTURES / "clean.xml").read_bytes())

    fetcher = _fetcher(handler)
    feeds = [
        Feed(id="good", url="https://good.example.com/rss"),
        Feed(id="bad", url="https://bad.example.com/rss"),
    ]
    results = {r.feed_id: r for r in await fetcher.fetch_many(feeds)}
    assert results["good"].ok and len(results["good"].items) == 2
    assert results["bad"].ok is False  # the batch survived the bad feed
