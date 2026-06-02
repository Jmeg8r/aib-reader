"""Tests for the deterministic dedup helpers."""

from __future__ import annotations

import pytest

from aib_reader.dedup import canonical_url, content_hash, is_same_story, title_similarity


def test_canonical_url_strips_tracking_and_www():
    a = "https://www.example.com/post/?utm_source=feedly&utm_medium=rss&id=42"
    b = "http://example.com/post?id=42"
    # tracking stripped, www stripped, but scheme differs -> still not identical;
    # canonicalization keeps scheme, so compare the tracking-stripped forms:
    assert canonical_url(a) == "https://example.com/post?id=42"
    assert canonical_url(b) == "http://example.com/post?id=42"


def test_canonical_url_same_article_across_feeds_matches():
    a = "https://example.com/2026/06/02/big-news/?utm_campaign=x&ref=twitter"
    b = "https://example.com/2026/06/02/big-news"
    assert canonical_url(a) == canonical_url(b)


def test_canonical_url_sorts_query_and_drops_fragment():
    assert canonical_url("https://e.com/p?b=2&a=1#section") == "https://e.com/p?a=1&b=2"


def test_canonical_url_trailing_slash_normalized():
    assert canonical_url("https://e.com/path/") == canonical_url("https://e.com/path")


def test_canonical_url_empty_and_garbage_total():
    assert canonical_url("") == ""
    assert canonical_url("not a url") == "not a url"


def test_content_hash_stable_and_case_insensitive():
    h1 = content_hash("Hello World", "A summary.")
    h2 = content_hash("hello world", "a summary.")
    assert h1 == h2
    assert content_hash("x", None) != content_hash("y", None)


def test_title_similarity_and_same_story():
    # Reordered/near-synonym titles score high (token_set_ratio handles word order).
    assert title_similarity("OpenAI launches GPT-6", "GPT-6 launched by OpenAI") >= 80
    assert is_same_story("Anthropic ships Claude 5", "Anthropic ships Claude 5 today")
    assert not is_same_story("Anthropic ships Claude 5", "Weather forecast for Tuesday")


@pytest.mark.parametrize("a,b", [(None, "x"), ("x", None), (None, None)])
def test_title_similarity_handles_none(a, b):
    assert title_similarity(a, b) == 0.0
