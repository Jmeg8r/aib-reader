# aib-reader

**Self-owned RSS aggregation substrate for the ASTGL ecosystem.**

A small Python library (plus a thin local-stdio MCP server) that ingests RSS/Atom
feeds, deduplicates across them, and answers "what's new on these sources?" queries
by category, time window, and keyword. Built because Feedly gates its developer API
behind an enterprise tier — so we own the aggregation layer instead.

> Status: **v0.0 — scaffold.** Public API and CLI surface are stubbed; the storage,
> fetch, and dedup logic land in v0.0b. See [`tasks/todo.md`](tasks/todo.md) for the
> build sequence and the design doc referenced there for the full rationale.

Not just for one project. The same store is queried by `aib-pipeline` (the daily
AI-news briefing), and is meant to be reused by UpdateKit, ASTGL article research,
and any Claude Code agent that needs "what changed on these feeds?"

---

## The contract (the part other projects depend on)

`aib-reader` is a **library first**. Consumers import it directly — no MCP transport,
no running server:

```python
from aib_reader import fetch_recent_items, mark_processed, Item

# Newest-first, dedupped, filtered to a category and time window.
items: list[Item] = fetch_recent_items(since="24h", limit=100, category="AI World")

# ... a consumer does its work ...

# Consumer-scoped cursor: marking these processed does NOT hide them from a
# different consumer (e.g. UpdateKit or a research agent).
mark_processed([i.id for i in items], consumer="aib-pipeline")
```

`since` accepts a suffix duration (`"24h"`, `"7d"`, `"2w"`) or an ISO-8601 timestamp.

## CLI

```bash
uv run aib-reader fetch            # poll all active feeds, store + dedup new items
uv run aib-reader list             # list configured feeds (URL, category, last fetch)
uv run aib-reader search "Anthropic"   # keyword search across stored items
uv run aib-reader doctor           # per-feed health; deactivate permanently-dead feeds
```

## MCP (for interactive Claude Code / agents)

A local-stdio MCP server exposes the same functions as five tools. Each tool maps
1:1 to a library function (`mcp_server.py` imports `api.py`, never the reverse — the
MCP SDK stays out of the library import path so the cron stays zero-overhead):

| MCP tool | Library function |
|---|---|
| `list_feeds()` | `list_feeds()` |
| `recent_items(limit, since, category)` | `fetch_recent_items(since, limit, category)` |
| `search_items(query, limit)` | `search_items(query, limit)` |
| `mark_processed(item_ids, consumer)` | `mark_processed(item_ids, consumer)` |
| `add_feed(url, category)` | `add_feed(url, category)` |

Register it user-scope in `~/.claude.json`:

```json
{
  "mcpServers": {
    "aib-reader": { "type": "stdio", "command": "aib-reader-mcp", "args": [], "env": {} }
  }
}
```

## Install (local dev)

```bash
uv sync --extra dev          # create venv + install deps
uv run aib-reader --help
uv run pytest
```

The feed list is `config/feeds.yaml` (generated from a Feedly OPML export; see
`config/feeds.yaml.example`). The SQLite store lives at `~/.aib-reader/store.db`.

## Design

Decisions (library-first, aggregation-query-only v1, all feeds ingested, from-scratch
SQLite behind a swappable `Store` interface, reference-not-adopt Horizon, consumer-scoped
cursors) are recorded in the approved design doc and mirrored in
[`tasks/todo.md`](tasks/todo.md).

## License

MIT
