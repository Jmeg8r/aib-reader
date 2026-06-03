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
    for name in ("fetch_recent_items", "mark_processed", "search_items", "list_feeds", "add_feed", "poll_feeds"):
        assert hasattr(aib_reader, name), f"missing public export: {name}"
    assert aib_reader.__version__ == "0.0.1"


def test_library_import_does_not_pull_in_mcp_sdk():
    # The cron imports the library; it must NOT drag in the mcp SDK. Assert this in a
    # FRESH interpreter — checking the shared pytest process is unreliable once
    # test_mcp_server.py (legitimately) imports the SDK in the same run.
    import subprocess
    import sys

    code = "import sys, aib_reader; assert 'mcp' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"library import pulled in the mcp SDK:\n{result.stderr}"


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


def test_cli_fetch_with_no_feeds_config_is_graceful(tmp_path, monkeypatch):
    # Isolate from the real config/feeds.yaml so the test never hits the network:
    # point at a non-existent feeds config -> poll_feeds returns an empty summary.
    monkeypatch.setenv("AIB_READER_DB_PATH", str(tmp_path / "f.db"))
    monkeypatch.setenv("AIB_READER_FEEDS_CONFIG", str(tmp_path / "missing.yaml"))
    result = runner.invoke(app, ["fetch"])
    assert result.exit_code == 0
    assert "0 feeds" in result.output
