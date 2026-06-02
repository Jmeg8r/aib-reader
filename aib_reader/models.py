"""Contract data models (pydantic v2).

These types ARE the integration contract between aib-reader and its consumers
(aib-pipeline now; UpdateKit, research agents later). Treat changes here as
versioned, breaking-API changes.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Feed(BaseModel):
    """A configured source. The feed list is canonical in config/feeds.yaml;
    the DB is a cache of it."""

    model_config = ConfigDict(frozen=False)

    id: str = Field(..., description="Stable feed id (hash of the feed URL).")
    url: str = Field(..., description="The feed (xmlUrl) to poll.")
    title: str | None = Field(None, description="Human title, from OPML or the feed.")
    site_url: str | None = Field(None, description="The site the feed belongs to.")
    categories: list[str] = Field(
        default_factory=list, description="Routing labels (a feed may have several)."
    )
    active: bool = Field(True, description="False = deactivated (e.g. permanently dead).")
    last_fetched_at: datetime | None = None
    # Conditional-GET cache validators (set after a successful fetch).
    etag: str | None = None
    modified: str | None = None


class Item(BaseModel):
    """A single feed entry (event), post-dedup.

    ``id`` is a STABLE surrogate = the dedup survivor's ``canonical_item_id``
    (deterministic hash of canonical_url, falling back to guid, then content_hash).
    It is NOT a SQLite rowid and it survives re-ingest. Marks/queries key on it.
    """

    model_config = ConfigDict(frozen=False)

    id: str = Field(..., description="Stable surrogate id (the dedup survivor).")
    feed_id: str
    feed_title: str | None = None
    url: str | None = Field(None, description="Original item URL.")
    canonical_url: str | None = Field(None, description="Normalized, tracking-stripped URL.")
    title: str | None = None
    summary: str | None = None
    author: str | None = None
    guid: str | None = None
    # Always timezone-aware UTC. Falls back to fetched_at when the feed omits a date.
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)


class RecentItemsQuery(BaseModel):
    """Parameters for a recent-items query. ``since`` accepts a suffix duration
    (``"24h"`` / ``"7d"`` / ``"2w"``) or an ISO-8601 timestamp."""

    since: str | None = Field("24h", description="Duration suffix or ISO-8601 timestamp.")
    limit: int = Field(100, ge=1, le=1000)
    category: str | None = Field(None, description="Exact category match if set.")
