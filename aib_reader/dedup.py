"""Deduplication helpers.

Strategy (per the design doc):
  1. canonical-URL exact match (normalize scheme/host, strip tracking params)
  2. content_hash fallback (title + summary)
  3. fuzzy title match within a short time window, same category, rapidfuzz ~92-95
Duplicates point at a survivor via ``canonical_item_id``.

This module implements the deterministic pure pieces now (``canonical_url``,
``content_hash``, ``title_similarity``). Cross-feed survivor selection over the
store lands in v0.0b.
"""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz

# WHAT: query params that are tracking noise, not content identity.
# WHY: the same article shared across feeds differs only by these — strip them
# so canonical URLs match.
_TRACKING_PREFIXES = ("utm_", "mc_", "mkt_", "pk_", "hsa_", "_hs")
_TRACKING_EXACT = {
    "ref",
    "ref_src",
    "ref_url",
    "source",
    "fbclid",
    "gclid",
    "igshid",
    "cmpid",
    "spm",
    "scid",
    "yclid",
    "wt_mc",
    "ncid",
}

# Default fuzzy-title threshold for "same story" (0-100). Tunable in v0.0b.
FUZZY_TITLE_THRESHOLD = 92


def _is_tracking_param(key: str) -> bool:
    k = key.lower()
    return k in _TRACKING_EXACT or k.startswith(_TRACKING_PREFIXES)


def canonical_url(url: str) -> str:
    """Normalize a URL for dedup: lowercase scheme/host, drop default ports and
    fragments, strip tracking params, and remove a trailing slash on the path.

    Best-effort and total: returns the input stripped if it cannot be parsed,
    never raises.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    host = (parts.hostname or "").lower()
    if not host:
        # No host -> not a canonicalizable URL (relative path or garbage).
        # Return it stripped rather than fabricating an "http:" scheme.
        return url.strip()

    scheme = (parts.scheme or "http").lower()
    if host.startswith("www."):
        host = host[4:]

    # Drop default ports.
    netloc = host
    if parts.port and not ((scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)):
        netloc = f"{host}:{parts.port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _is_tracking_param(k)]
    kept.sort()
    query = urlencode(kept)

    return urlunsplit((scheme, netloc, path, query, ""))  # fragment dropped


def content_hash(title: str | None, summary: str | None) -> str:
    """Stable fallback identity for items lacking a usable URL/guid."""
    basis = f"{(title or '').strip().lower()}\n{(summary or '').strip().lower()}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def title_similarity(a: str | None, b: str | None) -> float:
    """0-100 fuzzy similarity between two titles (token-set ratio handles reorderings)."""
    if not a or not b:
        return 0.0
    return float(fuzz.token_set_ratio(a, b))


def is_same_story(a: str | None, b: str | None, threshold: int = FUZZY_TITLE_THRESHOLD) -> bool:
    """Whether two titles are near-duplicates. Caller is responsible for bounding
    this to a short time window + same category (exact-duplicate suppression,
    NOT topic clustering)."""
    return title_similarity(a, b) >= threshold


def feed_id(url: str) -> str:
    """Stable 16-hex id for a feed URL (sha256 of its canonical_url).

    WHY: Feed identity must be deterministic and URL-based so the same id is
    produced whether the feed is first seen via OPML import or a later add_feed
    call. Consistent with the content_hash pattern above.
    """
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]


def item_surrogate_id(
    canonical_url_value: str | None,
    guid: str | None = None,
    content_hash_value: str | None = None,
) -> str:
    """Stable 16-hex surrogate id for an item: the dedup *survivor* key.

    Hashes the first available identity in priority order:
    ``canonical_url`` → ``guid`` → ``content_hash``. WHY this is the dedup
    keystone: two items sharing a canonical_url hash to the SAME id, so a
    PRIMARY KEY on items(id) + INSERT OR IGNORE collapses exact duplicates with
    no extra query. Fuzzy ("same story", different URL) duplicates get their own
    id and instead point ``canonical_item_id`` at the survivor.

    Raises ValueError if no identity is available — an item with no url, guid, or
    content is not addressable and must not be silently dropped.
    """
    basis = (canonical_url_value or "").strip() or (guid or "").strip() or (content_hash_value or "").strip()
    if not basis:
        raise ValueError("item_surrogate_id: need at least one of canonical_url, guid, content_hash")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
