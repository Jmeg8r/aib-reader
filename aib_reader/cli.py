"""Command-line interface (typer).

    aib-reader fetch    # poll feeds, store + dedup new items (v0.0b)
    aib-reader list     # list configured feeds
    aib-reader search   # keyword search stored items
    aib-reader doctor   # health check + store init

Heavy commands are stubbed until v0.0b; ``doctor`` works now and verifies the
install + store can be created.
"""

from __future__ import annotations

import typer

from aib_reader import __version__
from aib_reader._logging import get_logger

app = typer.Typer(
    help="Self-owned RSS aggregation for the ASTGL ecosystem.",
    no_args_is_help=True,
    add_completion=False,
)
log = get_logger(__name__)

_COMING = "Not yet implemented — lands in v0.0b. See tasks/todo.md."


@app.command()
def version() -> None:
    """Print the aib-reader version."""
    typer.echo(f"aib-reader {__version__}")


@app.command()
def fetch(
    category: str = typer.Option(None, "--category", "-c", help="Only poll this category."),
) -> None:
    """Poll active feeds, dedup, and store new items."""
    from aib_reader import api

    try:
        summary = api.poll_feeds(categories=[category] if category else None)
    except NotImplementedError:
        typer.secho(f"fetch: {_COMING}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=2)
    typer.echo(
        f"polled {summary.feeds_polled} feeds "
        f"({summary.feeds_failed} failed), {summary.new_items} new items"
    )


@app.command(name="list")
def list_feeds_cmd() -> None:
    """List configured feeds."""
    from aib_reader import api

    try:
        feeds = api.list_feeds()
    except NotImplementedError:
        typer.secho(f"list: {_COMING}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=2)
    for f in feeds:
        cats = ",".join(f.categories) or "-"
        typer.echo(f"{f.title or f.url}\t[{cats}]\t{f.url}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Keyword(s) to search stored items for."),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Keyword search across stored items."""
    from aib_reader import api

    try:
        items = api.search_items(query, limit=limit)
    except NotImplementedError:
        typer.secho(f"search: {_COMING}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=2)
    for it in items:
        typer.echo(f"{it.published_at}\t{it.title}\t{it.url}")


@app.command()
def doctor() -> None:
    """Health check: verify config, then create/inspect the local store."""
    from aib_reader.config import load_config
    from aib_reader.store.sqlite import SqliteStore

    cfg = load_config()
    typer.echo(f"db_path:       {cfg.db_path}")
    typer.echo(f"feeds_config:  {cfg.feeds_config}")
    typer.echo(f"user_agent:    {cfg.user_agent}")

    try:
        store = SqliteStore(cfg.db_path)
        store.init_schema()
        conn = store.connect()
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        store.close()
    except Exception as exc:  # surface, never swallow
        typer.secho(f"store: ERROR — {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho(f"store:         OK ({len(tables)} tables: {', '.join(tables)})", fg=typer.colors.GREEN)
    typer.secho("doctor:        scaffold OK. Per-feed health lands in v0.0b.", fg=typer.colors.GREEN)


if __name__ == "__main__":  # pragma: no cover
    app()
