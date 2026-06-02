"""Scaffold smoke tests: imports, contract types, store schema, CLI."""

from __future__ import annotations

from datetime import datetime, timezone

from typer.testing import CliRunner

import aib_reader
from aib_reader.cli import app
from aib_reader.models import Feed, Item
from aib_reader.store.sqlite import SqliteStore

runner = CliRunner()


def test_public_contract_is_importable():
    for name in ("fetch_recent_items", "mark_processed", "search_items", "list_feeds", "add_feed"):
        assert hasattr(aib_reader, name), f"missing public export: {name}"
    assert aib_reader.__version__ == "0.0.1"


def test_library_import_does_not_pull_in_mcp_sdk():
    # The cron imports the library; it must NOT drag in the mcp SDK.
    import sys

    assert "mcp" not in sys.modules, "importing aib_reader must not import the mcp SDK"


def test_models_construct():
    feed = Feed(id="f1", url="https://e.com/rss", categories=["AI World"])
    item = Item(
        id="i1",
        feed_id="f1",
        title="hello",
        published_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )
    assert feed.active is True
    assert item.categories == []
    assert item.id == "i1"


def test_sqlite_store_init_schema_creates_tables(tmp_path):
    store = SqliteStore(tmp_path / "store.db")
    store.init_schema()
    conn = store.connect()
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    store.close()
    assert {"feeds", "categories", "feed_categories", "items", "processed_items"} <= tables


def test_cli_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "aib-reader" in result.output.lower() or "Usage" in result.output


def test_cli_doctor_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AIB_READER_DB_PATH", str(tmp_path / "doctor.db"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "store:" in result.output
    assert "OK" in result.output


def test_cli_fetch_reports_not_implemented(tmp_path, monkeypatch):
    monkeypatch.setenv("AIB_READER_DB_PATH", str(tmp_path / "f.db"))
    result = runner.invoke(app, ["fetch"])
    # poll_feeds is a v0.0b stub -> graceful exit code 2, not a crash.
    assert result.exit_code == 2
