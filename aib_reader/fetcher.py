"""Feed fetching.

The ``Fetcher`` Protocol abstracts retrieval so the store/dedup layers don't care
how bytes arrive. The v1 implementation is a bounded-async httpx client with
conditional GET (ETag / Last-Modified), per-feed timeout, and per-feed error
isolation — one bad feed never aborts the whole ingest.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import unquote, urlencode, urlsplit

import feedparser
import httpx

from aib_reader._logging import get_logger
from aib_reader._time import now_utc
from aib_reader.dedup import canonical_url, content_hash, item_surrogate_id
from aib_reader.models import Feed, Item

log = get_logger(__name__)


# WHAT: the legacy Reddit API host that Feedly exports subscriptions against.
# WHY: api.reddit.com 403s unauthenticated clients (OAuth-only now), and Feedly's
# paths there (/subreddit/<X>, /search/<q>;<sort>/<uuid>) aren't real RSS endpoints
# anyway. Reddit serves working public RSS from www.reddit.com. See normalize_feed_url.
_REDDIT_API_HOST = "api.reddit.com"


def normalize_feed_url(url: str) -> str:
    """Rewrite known unfetchable feed-host quirks to a working RSS endpoint.

    Currently handles Feedly's ``api.reddit.com`` export forms, translating them to
    the public ``www.reddit.com`` RSS endpoints that actually serve XML:

    - ``api.reddit.com/subreddit/<name>``        -> ``www.reddit.com/r/<name>/.rss``
    - ``api.reddit.com/subreddit/<name>;top``    -> ``.../r/<name>/top/.rss?t=day``
    - ``api.reddit.com/subreddit/<name>;<sort>`` -> ``.../r/<name>/<sort>/.rss``
    - ``api.reddit.com/search/<q>;<sort>/<uuid>``-> ``.../search.rss?q=<q>&sort=<sort>``

    Anything else — including already-correct ``www.reddit.com/.../.rss`` URLs and
    every non-Reddit feed — is returned unchanged. Pure and side-effect free so the
    fetcher can log the rewrite and tests can assert it directly.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if (parts.hostname or "").lower() != _REDDIT_API_HOST:
        return url

    path = parts.path.strip("/")

    if path.startswith("subreddit/"):
        # spec is "<name>" or "<name>;<sort>" (Feedly's sort suffix).
        name, _, sort = path[len("subreddit/"):].partition(";")
        name = name.strip("/")
        if not name:
            return url  # malformed; leave it for the caller to error on
        if sort == "top":
            # "top" needs a time window; "day" matches Feedly's default top feed.
            return f"https://www.reddit.com/r/{name}/top/.rss?t=day"
        if sort:
            return f"https://www.reddit.com/r/{name}/{sort}/.rss"
        return f"https://www.reddit.com/r/{name}/.rss"

    if path.startswith("search/"):
        # spec is "<query>;<sort>" optionally followed by "/<feedly-uuid>" — drop the uuid.
        spec = path[len("search/"):].split("/", 1)[0]
        query_raw, _, sort = spec.partition(";")
        # Feedly percent-encodes the query (e.g. "Home%20Assistant"); decode then re-encode
        # cleanly to avoid double-encoding.
        params = {"q": unquote(query_raw)}
        if sort:
            params["sort"] = sort
        return f"https://www.reddit.com/search.rss?{urlencode(params)}"

    return url


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


def _struct_time_to_utc(st: time.struct_time | None) -> datetime | None:
    """Convert a feedparser ``*_parsed`` struct_time (always UTC) to an aware UTC
    datetime, or None."""
    if st is None:
        return None
    try:
        return datetime(*st[:6], tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_entry_date(entry: feedparser.FeedParserDict, *, feed_title: str | None) -> datetime | None:
    """Port of Horizon's date-parsing fallback chain, hardened.

    Prefer the structured ``*_parsed`` fields (already UTC) in published → updated
    → created order; fall back to string parsing. Returns None (and logs a
    warning) when no usable date exists — the caller stores NULL and queries
    coalesce to ``fetched_at`` so the item never silently vanishes from a
    time-window query.
    """
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        dt = _struct_time_to_utc(entry.get(key))
        if dt is not None:
            return dt

    # String fallback via dateutil (handles odd but parseable formats).
    from dateutil import parser as _dateparser

    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if raw:
            try:
                parsed = _dateparser.parse(raw)
                return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (ValueError, OverflowError, TypeError):
                continue

    log.warning("no parseable date for entry %r in feed %s — will fall back to fetched_at",
                entry.get("title", "<untitled>"), feed_title)
    return None


def _entry_to_item(entry: feedparser.FeedParserDict, feed: Feed, fetched_at: datetime) -> Item:
    """Build a contract ``Item`` from a feedparser entry, computing its dedup id."""
    url = (entry.get("link") or "").strip() or None
    guid = (entry.get("id") or "").strip() or None
    title = (entry.get("title") or "").strip() or None
    summary = (entry.get("summary") or "").strip() or None
    author = (entry.get("author") or "").strip() or None

    canon = canonical_url(url) if url else ""
    chash = content_hash(title, summary)
    surrogate = item_surrogate_id(canon or None, guid, chash)

    return Item(
        id=surrogate,
        feed_id=feed.id,
        feed_title=feed.title,
        url=url,
        canonical_url=canon or None,
        title=title,
        summary=summary,
        author=author,
        guid=guid,
        published_at=_parse_entry_date(entry, feed_title=feed.title),
        fetched_at=fetched_at,
        categories=list(feed.categories),
    )


class HttpxFetcher:
    """Bounded-async httpx fetcher with conditional GET and per-feed isolation."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        concurrency: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.concurrency = concurrency
        # WHY: tests inject an httpx.MockTransport so unit tests never hit the network.
        self.transport = transport

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
            follow_redirects=True,
            transport=self.transport,
        )

    async def fetch_feed(self, feed: Feed, *, client: httpx.AsyncClient | None = None) -> FetchResult:
        own_client = client is None
        if own_client:
            client = self._new_client()
        try:
            return await self._fetch_one(feed, client)
        finally:
            if own_client:
                await client.aclose()

    async def _fetch_one(self, feed: Feed, client: httpx.AsyncClient) -> FetchResult:
        headers: dict[str, str] = {}
        if feed.etag:
            headers["If-None-Match"] = feed.etag
        if feed.modified:
            headers["If-Modified-Since"] = feed.modified

        request_url = normalize_feed_url(feed.url)
        if request_url != feed.url:
            log.info("normalized feed url %s -> %s", feed.url, request_url)

        try:
            resp = await client.get(request_url, headers=headers)
        except httpx.HTTPError as exc:
            return FetchResult(feed_id=feed.id, ok=False, error=f"{type(exc).__name__}: {exc}")

        if resp.status_code == 304:
            log.debug("feed %s not modified (304)", feed.title or feed.url)
            return FetchResult(feed_id=feed.id, ok=True, status=304, not_modified=True)

        if resp.status_code >= 400:
            return FetchResult(
                feed_id=feed.id, ok=False, status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )

        fetched_at = now_utc()
        try:
            parsed = feedparser.parse(resp.content)
        except Exception as exc:  # feedparser is tolerant but guard anyway
            return FetchResult(feed_id=feed.id, ok=False, status=resp.status_code,
                               error=f"parse error: {type(exc).__name__}: {exc}")

        # feedparser sets .bozo on malformed XML but usually still yields entries;
        # only treat it as failure when nothing was salvageable.
        if parsed.bozo and not parsed.entries:
            reason = getattr(parsed, "bozo_exception", "malformed feed")
            return FetchResult(feed_id=feed.id, ok=False, status=resp.status_code,
                               error=f"unparseable: {reason}")

        items = [_entry_to_item(e, feed, fetched_at) for e in parsed.entries]
        log.info("fetched %s: %d entries (status %d)", feed.title or feed.url, len(items), resp.status_code)
        return FetchResult(
            feed_id=feed.id,
            ok=True,
            items=items,
            status=resp.status_code,
            etag=resp.headers.get("ETag"),
            modified=resp.headers.get("Last-Modified"),
        )

    async def fetch_many(self, feeds: list[Feed]) -> list[FetchResult]:
        """Poll feeds concurrently, bounded by a semaphore. One shared client."""
        sem = asyncio.Semaphore(self.concurrency)
        async with self._new_client() as client:

            async def _guarded(feed: Feed) -> FetchResult:
                async with sem:
                    return await self._fetch_one(feed, client)

            return await asyncio.gather(*(_guarded(f) for f in feeds))
