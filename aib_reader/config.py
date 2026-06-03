"""Runtime configuration (paths + tunables), centralized.

WHY: one place resolves env knobs so the store, fetcher, CLI, and MCP server all
agree on where things live. No magic numbers scattered across modules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# WHAT: defaults. WHY: documented, overridable via env (see .env.example).
DEFAULT_DB_PATH = Path.home() / ".aib-reader" / "store.db"
DEFAULT_FEEDS_CONFIG = Path("config/feeds.yaml")
DEFAULT_USER_AGENT = "aib-reader/0.0.1 (+https://github.com/jmeg8r/aib-reader)"
DEFAULT_FETCH_CONCURRENCY = 10
DEFAULT_FETCH_TIMEOUT = 20.0  # seconds, per feed
DEFAULT_FIRST_FETCH_HORIZON_DAYS = 14  # cap historical items on a feed's first poll
DEFAULT_DEAD_FEED_THRESHOLD = 5  # consecutive failures before doctor flags/deactivates a feed


@dataclass(frozen=True)
class Config:
    db_path: Path
    feeds_config: Path
    user_agent: str
    fetch_concurrency: int
    fetch_timeout: float
    first_fetch_horizon_days: int


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).expanduser()


def load_config() -> Config:
    """Resolve config from environment, falling back to defaults."""
    return Config(
        db_path=_expand(os.environ.get("AIB_READER_DB_PATH", str(DEFAULT_DB_PATH))),
        feeds_config=_expand(
            os.environ.get("AIB_READER_FEEDS_CONFIG", str(DEFAULT_FEEDS_CONFIG))
        ),
        user_agent=os.environ.get("AIB_READER_USER_AGENT", DEFAULT_USER_AGENT),
        fetch_concurrency=int(
            os.environ.get("AIB_READER_FETCH_CONCURRENCY", DEFAULT_FETCH_CONCURRENCY)
        ),
        fetch_timeout=float(
            os.environ.get("AIB_READER_FETCH_TIMEOUT", DEFAULT_FETCH_TIMEOUT)
        ),
        first_fetch_horizon_days=int(
            os.environ.get(
                "AIB_READER_FIRST_FETCH_HORIZON_DAYS", DEFAULT_FIRST_FETCH_HORIZON_DAYS
            )
        ),
    )
