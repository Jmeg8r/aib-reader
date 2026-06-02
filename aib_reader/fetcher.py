"""Feed fetching.

The ``Fetcher`` Protocol abstracts retrieval so the store/dedup layers don't care
how bytes arrive. The v1 implementation (v0.0b) is a bounded-async httpx client
with conditional GET (ETag / Last-Modified), per-feed timeout, and per-feed error
isolation — one bad feed never aborts the whole ingest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from aib_reader.models import Feed, Item


@dataclass
class FetchResult:
    """Outcome of polling one feed. ``ok=False`` carries the error, never raises
    out of the batch — that's how per-feed isolation works."""

    feed_id: str
    ok: bool
    items: list[Item] = field(default_factory=list)
    status: int | None = None
    not_modified: bool = False  # 304 from conditional GET
    etag: str | None = None
    modified: str | None = None
    error: str | None = None


class Fetcher(Protocol):
    async def fetch_feed(self, feed: Feed) -> FetchResult:
        """Poll a single feed. Must not raise for network/parse errors —
        return ``FetchResult(ok=False, error=...)`` instead."""
        ...


_NOT_YET = "implemented in v0.0b (see tasks/todo.md)"


class HttpxFetcher:
    """Bounded-async httpx fetcher. Stub — real impl in v0.0b."""

    def __init__(self, *, user_agent: str, timeout: float, concurrency: int) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.concurrency = concurrency

    async def fetch_feed(self, feed: Feed) -> FetchResult:
        raise NotImplementedError(f"HttpxFetcher.fetch_feed: {_NOT_YET}")
