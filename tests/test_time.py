"""Tests for the strict `since` parser and UTC normalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aib_reader._time import parse_since, to_utc

_NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "since, expected_delta",
    [
        ("24h", timedelta(hours=24)),
        ("1h", timedelta(hours=1)),
        ("7d", timedelta(days=7)),
        ("2w", timedelta(weeks=2)),
        ("  3d ", timedelta(days=3)),  # whitespace tolerant
    ],
)
def test_parse_since_durations(since, expected_delta):
    assert parse_since(since, now=_NOW) == _NOW - expected_delta


def test_parse_since_iso8601():
    assert parse_since("2026-06-01T00:00:00Z", now=_NOW) == datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )


def test_parse_since_iso_naive_is_utc():
    # Naive ISO input is treated as UTC.
    assert parse_since("2026-06-01T00:00:00", now=_NOW).tzinfo == timezone.utc


@pytest.mark.parametrize("bad", ["", "  ", "soon", "10x", "yesterday", "5"])
def test_parse_since_invalid_raises(bad):
    with pytest.raises(ValueError):
        parse_since(bad, now=_NOW)


def test_to_utc_naive_assumed_utc():
    naive = datetime(2026, 6, 2, 12, 0, 0)
    assert to_utc(naive) == _NOW


def test_to_utc_converts_offset():
    eastern = datetime(2026, 6, 2, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert to_utc(eastern) == _NOW
