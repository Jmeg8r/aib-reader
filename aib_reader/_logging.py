"""Structured logging setup.

WHY: logging is mandatory in this project (no silent failures). Every fetch,
dedup decision, and MCP tool call logs. Consumers get a configured logger via
``get_logger(__name__)``; the level is driven by ``AIB_READER_LOG_LEVEL``.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False
_DEFAULT_LEVEL = "INFO"


def _configure_root() -> None:
    """Configure the package root logger once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.environ.get("AIB_READER_LOG_LEVEL", _DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("aib_reader")
    root.setLevel(level)

    # Log to stderr so stdout stays clean for MCP stdio transport and CLI piping.
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger namespaced under ``aib_reader``."""
    _configure_root()
    # Normalize "aib_reader.x" or "__main__" to a stable child name.
    if not name.startswith("aib_reader"):
        name = f"aib_reader.{name.split('.')[-1]}"
    return logging.getLogger(name)
