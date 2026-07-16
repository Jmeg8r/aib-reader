"""Tests for the MCP server wrapper.

This is the ONE test module that imports the `mcp` SDK — mirroring how
`mcp_server.py` is the only library module that does. Verifies the 7 tools are
registered and each delegates 1:1 to `aib_reader.api`, returning JSON-safe shapes
(plain dict/list/int/bool — never pydantic or dataclass objects leaking over the
wire)."""

from __future__ import annotations

import asyncio
import dataclasses

from aib_reader import mcp_server
from aib_reader.api import PollSummary
from aib_reader.models import Feed, Item

EXPECTED_TOOLS = {
    "list_feeds",
    "recent_items",
    "search_items",
    "mark_processed",
    "add_feed",
    "remove_feed",
    "poll_feeds",
}


def test_exactly_seven_tools_registered():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS


def test_list_feeds_delegates_and_returns_json(monkeypatch):
    monkeypatch.setattr(
        mcp_server.api, "list_feeds",
        lambda: [Feed(id="f1", url="https://e.com/rss", categories=["AI World"])],
    )
    out = mcp_server.list_feeds()
    assert isinstance(out, list) and isinstance(out[0], dict)
    assert out[0]["url"] == "https://e.com/rss"
    assert out[0]["categories"] == ["AI World"]


def test_recent_items_reorders_args_to_library(monkeypatch):
    captured = {}

    def fake(since, limit, category):  # library signature: (since, limit, category)
        captured.update(since=since, limit=limit, category=category)
        return [Item(id="i1", feed_id="f1", title="x")]

    monkeypatch.setattr(mcp_server.api, "fetch_recent_items", fake)
    # MCP signature is (limit, since, category) — the intentional ergonomic reorder.
    out = mcp_server.recent_items(limit=10, since="7d", category="AI World")
    assert captured == {"since": "7d", "limit": 10, "category": "AI World"}
    assert isinstance(out, list) and isinstance(out[0], dict) and out[0]["id"] == "i1"


def test_search_items_delegates(monkeypatch):
    captured = {}

    def fake(query, limit):
        captured.update(query=query, limit=limit)
        return [Item(id="i2", feed_id="f1", title="Anthropic")]

    monkeypatch.setattr(mcp_server.api, "search_items", fake)
    out = mcp_server.search_items("Anthropic", limit=25)
    assert captured == {"query": "Anthropic", "limit": 25}
    assert out[0]["title"] == "Anthropic"


def test_mark_processed_delegates_and_returns_int(monkeypatch):
    captured = {}

    def fake(item_ids, consumer):
        captured.update(item_ids=item_ids, consumer=consumer)
        return len(item_ids)

    monkeypatch.setattr(mcp_server.api, "mark_processed", fake)
    out = mcp_server.mark_processed(["a", "b"], consumer="aib-pipeline")
    assert out == 2
    assert captured == {"item_ids": ["a", "b"], "consumer": "aib-pipeline"}


def test_add_feed_delegates_and_returns_dict(monkeypatch):
    captured = {}

    def fake(url, category=None):
        captured.update(url=url, category=category)
        return Feed(id="f9", url=url, categories=[category] if category else [])

    monkeypatch.setattr(mcp_server.api, "add_feed", fake)
    out = mcp_server.add_feed("https://new.example.com/rss", category="tech")
    assert isinstance(out, dict) and out["url"] == "https://new.example.com/rss"
    assert captured == {"url": "https://new.example.com/rss", "category": "tech"}


def test_remove_feed_delegates_and_returns_bool(monkeypatch):
    captured = {}

    def fake(url):
        captured.update(url=url)
        return True

    monkeypatch.setattr(mcp_server.api, "remove_feed", fake)
    out = mcp_server.remove_feed("https://old.example.com/rss")
    assert out is True
    assert captured == {"url": "https://old.example.com/rss"}


def test_poll_feeds_delegates_and_returns_plain_dict(monkeypatch):
    captured = {}

    def fake(categories=None):
        captured.update(categories=categories)
        return PollSummary(feeds_polled=3, feeds_failed=1, new_items=7)

    monkeypatch.setattr(mcp_server.api, "poll_feeds", fake)
    out = mcp_server.poll_feeds(categories=["AI World"])
    # A plain dict crosses the wire — the PollSummary dataclass must not leak.
    assert out == {"feeds_polled": 3, "feeds_failed": 1, "new_items": 7}
    assert not dataclasses.is_dataclass(out)
    assert captured == {"categories": ["AI World"]}
