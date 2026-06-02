"""Time helpers: strict ``since`` parsing and UTC normalization.

WHY: time-window queries are only correct if every timestamp is timezone-aware
UTC and ``since`` has one unambiguous grammar. Invalid input raises (no silent
default) per the design contract.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from dateutil import parser as _dateparser

_SINCE_RE = re.compile(r"^\s*(\d+)\s*([hdw])\s*$", re.IGNORECASE)
_UNIT_TO_HOURS = {"h": 1, "d": 24, "w": 24 * 7}


def to_utc(dt: datetime) -> datetime:
    """Return ``dt`` as timezone-aware UTC. Naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_since(since: str, *, now: datetime | None = None) -> datetime:
    """Resolve a ``since`` argument to a UTC cutoff datetime (the lower bound).

    Accepts a suffix duration (``"24h"``, ``"7d"``, ``"2w"``) interpreted as
    "now minus that span", or an absolute ISO-8601 timestamp. Raises
    ``ValueError`` on anything else — there is no silent default.
    """
    if since is None or not str(since).strip():
        raise ValueError("`since` is required (e.g. '24h', '7d', or an ISO-8601 timestamp)")

    now = to_utc(now) if now is not None else now_utc()

    m = _SINCE_RE.match(str(since))
    if m:
        qty = int(m.group(1))
        hours = qty * _UNIT_TO_HOURS[m.group(2).lower()]
        return now - timedelta(hours=hours)

    # Fall back to absolute ISO-8601.
    try:
        parsed = _dateparser.isoparse(str(since))
    except (ValueError, OverflowError) as exc:
        raise ValueError(
            f"invalid `since`={since!r}: expected duration like '24h'/'7d'/'2w' "
            f"or an ISO-8601 timestamp"
        ) from exc
    return to_utc(parsed)
