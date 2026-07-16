# CLAUDE.md — aib-reader (project-specific overrides)

Self-owned RSS aggregation substrate for the ASTGL ecosystem. A Python **library
first** (importable, zero transport overhead) + a thin local-stdio **MCP** wrapper.
The sibling `aib-pipeline` imports this as a library for its daily 4am cron.

Global conventions in `~/.claude/CLAUDE.md` still apply. This file adds project rules.

## The contract is sacred

The public API is the seam that other projects build on. Do not break it casually:

```python
from aib_reader import fetch_recent_items, mark_processed, Item
```

- Every MCP tool maps 1:1 to a library function (see README table).
- `mcp_server.py` imports `api.py`, **never the reverse** — keep the `mcp` SDK out of
  the library import path so `from aib_reader import ...` stays MCP-free and fast.
- `mark_processed` is **consumer-scoped** (`processed_items(consumer, item_id)`). One
  consumer marking an item processed must never hide it from another.
- Marks and queries key on the dedup **survivor** (`canonical_item_id`); `Item.id` is a
  stable surrogate, not a SQLite rowid.

## Scope (v1)

In: ingest all OPML feeds, dedup, query by category/time/keyword, `mark_processed`,
typer CLI (`fetch`/`list`/`search`/`doctor`), the 7-tool MCP server.
Out (v1): web UI, per-item read/star state, AI scoring/enrichment, HTTP MCP transport,
a Miniflux/FreshRSS backend (keep the `Store` interface clean for it later), PyPI.

## Engineering rules (this repo)

- **Python:** `snake_case` funcs/vars, `PascalCase` classes, `SCREAMING_SNAKE_CASE`
  constants. Type hints everywhere. `typing.Protocol` for `Store`/`Fetcher`.
- **Logging is mandatory.** Use the stdlib `logging` setup in `aib_reader/_logging.py`.
  Log every fetch, every dedup decision, every MCP tool call. No silent failures.
- **No bare `except:`.** Catch specific exceptions; per-feed errors are isolated and
  logged, never allowed to abort a whole ingest.
- **Timestamps are timezone-aware UTC**, stored ISO-8601. Null/unparseable
  `published_at` falls back to `fetched_at` (and logs a warning).
- **Tests are mandatory** (pytest). Test against a fixture OPML + a handful of
  deliberately ugly real feeds.
- **`config/feeds.yaml` is canonical** for the feed list; the DB is a cache of it.

## Workflow

- Feature/chore branches (`feat/`, `fix/`, `chore/`, `docs/`). **Never commit to `main`
  directly; never push to `main`.** Conventional, atomic commits.
- gitignore secrets FIRST. The store DB and `.env` are gitignored.
- Verify before done: `uv run pytest` green, `uv run aib-reader doctor` clean, and the
  contract demonstrated end-to-end before marking a milestone complete.

## Build sequence

v0.0a (Horizon eval → `docs/horizon-evaluation.md`) → v0.0b (library) → v0.0c (MCP +
register) → integration handshake with aib-pipeline. Detail in `tasks/todo.md`.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool.
- Product/scope rethink → `/office-hours`
- Architecture pressure-test → `/plan-eng-review`
- Bugs/errors → `/investigate`
- QA a behavior → `/qa`
- Code review a diff → `/review`
- Ship/PR → `/ship`
