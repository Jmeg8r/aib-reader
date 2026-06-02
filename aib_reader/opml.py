"""OPML import.

Parses a Feedly OPML export into ``Feed`` records (all categories, category-first),
preserving the export verbatim as the seed for ``config/feeds.yaml``. Real parsing
lands in v0.0b prep (task #3); the signature is fixed here so callers can target it.
"""

from __future__ import annotations

from pathlib import Path

from aib_reader.models import Feed

_NOT_YET = "implemented in v0.0b prep (see tasks/todo.md, task #3)"


def parse_opml(path: Path) -> list[Feed]:
    """Parse an OPML file into ``Feed`` records.

    Nested ``<outline>`` elements are categories; leaf outlines with an ``xmlUrl``
    are feeds. A feed may appear under multiple categories.
    """
    raise NotImplementedError(f"parse_opml: {_NOT_YET}")


def opml_to_feeds_yaml(opml_path: Path, yaml_path: Path) -> int:
    """Convert an OPML export to the canonical ``config/feeds.yaml``. Returns the
    number of feeds written."""
    raise NotImplementedError(f"opml_to_feeds_yaml: {_NOT_YET}")
