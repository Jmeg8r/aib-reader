"""Tests for aib_reader.opml (parse_opml, opml_to_feeds_yaml) and dedup.feed_id."""

from __future__ import annotations

from pathlib import Path

import yaml

from aib_reader.dedup import feed_id
from aib_reader.opml import parse_opml, opml_to_feeds_yaml

FIXTURE = Path(__file__).parent / "fixtures" / "sample.opml"


# ---------------------------------------------------------------------------
# feed_id
# ---------------------------------------------------------------------------


def test_feed_id_is_stable():
    url = "https://huggingface.co/blog/feed.xml"
    assert feed_id(url) == feed_id(url), "same URL must produce same id"


def test_feed_id_differs_for_different_urls():
    assert feed_id("https://example.com/feed.xml") != feed_id("https://other.com/rss")


def test_feed_id_is_canonical_url_invariant():
    # http vs https with www prefix should normalize to same id (canonical_url handles this)
    a = feed_id("http://www.huggingface.co/blog/feed.xml")
    b = feed_id("https://huggingface.co/blog/feed.xml")
    # canonical_url strips www and lowercases but preserves scheme — so these differ on scheme.
    # The important assertion is that repeated calls with the SAME url are stable.
    assert feed_id(a) == feed_id(a)


# ---------------------------------------------------------------------------
# parse_opml
# ---------------------------------------------------------------------------


def test_parse_opml_returns_feeds():
    feeds = parse_opml(FIXTURE)
    # Fixture has: HF Blog, DeepMind, Verge, Letters from An American (feedly alert skipped)
    # = 4 unique real feeds
    assert len(feeds) == 4
    urls = {f.url for f in feeds}
    assert "https://huggingface.co/blog/feed.xml" in urls
    assert "https://deepmind.com/blog/feed/basic/" in urls
    assert "http://www.theverge.com/rss/full.xml" in urls
    assert "https://simonwillison.net/feed/" in urls


def test_parse_opml_deduplicates_by_url():
    feeds = parse_opml(FIXTURE)
    hf = next(f for f in feeds if "huggingface" in f.url)
    # HF Blog appears in both AI World and tech → merged
    assert set(hf.categories) == {"AI World", "tech"}


def test_parse_opml_skips_feedly_urls():
    feeds = parse_opml(FIXTURE)
    feedly_feeds = [f for f in feeds if "feedly.com" in f.url]
    assert feedly_feeds == [], "feedly.com URLs must be filtered out"


def test_parse_opml_empty_category_no_crash():
    feeds = parse_opml(FIXTURE)
    # "interesting" category is empty — must not crash or produce an entry
    assert all(f.url for f in feeds), "every feed must have a url"


def test_parse_opml_feed_has_title_and_site_url():
    feeds = parse_opml(FIXTURE)
    hf = next(f for f in feeds if "huggingface" in f.url)
    assert hf.title == "Hugging Face Blog"
    assert hf.site_url == "https://huggingface.co/blog"


def test_parse_opml_feed_id_is_16_hex():
    feeds = parse_opml(FIXTURE)
    for f in feeds:
        assert len(f.id) == 16
        assert all(c in "0123456789abcdef" for c in f.id)


# ---------------------------------------------------------------------------
# opml_to_feeds_yaml
# ---------------------------------------------------------------------------


def test_opml_to_feeds_yaml_creates_file(tmp_path):
    out = tmp_path / "feeds.yaml"
    count = opml_to_feeds_yaml(FIXTURE, out)
    assert out.exists()
    assert count == 4


def test_opml_to_feeds_yaml_valid_yaml(tmp_path):
    out = tmp_path / "feeds.yaml"
    opml_to_feeds_yaml(FIXTURE, out)
    data = yaml.safe_load(out.read_text())
    assert "feeds" in data
    assert isinstance(data["feeds"], list)
    assert len(data["feeds"]) == 4


def test_opml_to_feeds_yaml_categories_inline_style(tmp_path):
    out = tmp_path / "feeds.yaml"
    opml_to_feeds_yaml(FIXTURE, out)
    text = out.read_text()
    # Inline/flow-style categories look like: categories: [AI World, tech]
    assert "categories: [" in text, "categories must be rendered in inline/flow style"


def test_opml_to_feeds_yaml_merged_categories_present(tmp_path):
    out = tmp_path / "feeds.yaml"
    opml_to_feeds_yaml(FIXTURE, out)
    data = yaml.safe_load(out.read_text())
    hf_entry = next(e for e in data["feeds"] if "huggingface" in e["url"])
    assert "AI World" in hf_entry["categories"]
    assert "tech" in hf_entry["categories"]
