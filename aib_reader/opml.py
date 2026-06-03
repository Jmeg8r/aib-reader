"""OPML import.

Parses a Feedly OPML export into ``Feed`` records (all categories, category-first),
preserving the export verbatim as the seed for ``config/feeds.yaml``.

Design notes (from docs/horizon-evaluation.md and CLAUDE.md):
- A feed may belong to multiple categories; we merge them into one entry.
- Feedly-internal proxy URLs (hostname feedly.com) are skipped — they return 403
  outside of Feedly and have no fetchable RSS endpoint.
- Parsing uses stdlib xml.etree.ElementTree; no new dependency required.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from aib_reader._logging import get_logger
from aib_reader.dedup import canonical_url, feed_id
from aib_reader.models import Feed

log = get_logger(__name__)


# WHAT: detect Feedly-internal proxy URLs by hostname.
# WHY: feedly.com/f/alert/... and feedly.com/email/... are personal subscription
# proxies that return 403 outside the Feedly service — skip them with a warning.
_FEEDLY_HOST = "feedly.com"


def _is_feedly_internal(url: str) -> bool:
    try:
        host = urlsplit(url).hostname or ""
        return host == _FEEDLY_HOST or host.endswith(f".{_FEEDLY_HOST}")
    except ValueError:
        return False


class _FlowList(list):
    """A list subclass that PyYAML renders in inline/flow style: [a, b, c]."""


def _flow_list_representer(dumper: yaml.Dumper, data: _FlowList) -> yaml.Node:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def parse_opml(path: Path) -> list[Feed]:
    """Parse an OPML file into ``Feed`` records.

    Nested ``<outline>`` elements are categories; leaf outlines with an ``xmlUrl``
    are feeds. A feed may appear under multiple categories — those appearances are
    merged into a single ``Feed`` with all categories listed.
    """
    tree = ET.parse(path)
    body = tree.getroot().find("body")
    if body is None:
        log.warning("opml %s: no <body> element — returning empty list", path)
        return []

    # Keyed by canonical_url so cross-category duplicates are merged.
    seen: dict[str, Feed] = {}
    skipped_feedly = 0

    for category_outline in body:
        category = (category_outline.get("title") or category_outline.get("text") or "").strip()

        for feed_outline in category_outline:
            xml_url = feed_outline.get("xmlUrl", "").strip()
            if not xml_url:
                continue

            if _is_feedly_internal(xml_url):
                title = feed_outline.get("title") or feed_outline.get("text") or xml_url
                log.warning("skipping feedly-internal URL (not fetchable): %s — %s", title, xml_url)
                skipped_feedly += 1
                continue

            key = canonical_url(xml_url)
            if key in seen:
                # Merge category into existing entry.
                if category and category not in seen[key].categories:
                    seen[key].categories.append(category)
            else:
                title = (feed_outline.get("title") or feed_outline.get("text") or "").strip() or None
                site_url = feed_outline.get("htmlUrl", "").strip() or None
                cats = [category] if category else []
                seen[key] = Feed(
                    id=feed_id(xml_url),
                    url=xml_url,
                    title=title,
                    site_url=site_url,
                    categories=cats,
                )

    if skipped_feedly:
        log.info("parse_opml: skipped %d feedly-internal URLs", skipped_feedly)

    feeds = list(seen.values())
    log.info("parse_opml: %s → %d feeds (%d skipped feedly)", path.name, len(feeds), skipped_feedly)
    return feeds


def opml_to_feeds_yaml(opml_path: Path, yaml_path: Path) -> int:
    """Convert an OPML export to the canonical ``config/feeds.yaml``. Returns the
    number of feeds written."""
    feeds = parse_opml(opml_path)

    yaml.add_representer(_FlowList, _flow_list_representer)

    records = []
    for f in feeds:
        entry: dict = {"url": f.url}
        if f.title:
            entry["title"] = f.title
        entry["categories"] = _FlowList(f.categories)
        records.append(entry)

    header = (
        f"# Generated from {opml_path.name} — edit manually or re-run import-opml to regenerate.\n"
        "# Schema: url (required), title (optional), categories (routing labels).\n"
    )

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with yaml_path.open("w", encoding="utf-8") as fh:
        fh.write(header)
        yaml.dump({"feeds": records}, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    log.info("opml_to_feeds_yaml: wrote %d feeds to %s", len(feeds), yaml_path)
    return len(feeds)
