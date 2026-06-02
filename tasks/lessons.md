# Lessons — aib-reader

Per global CLAUDE.md: capture patterns after corrections so the same mistake
doesn't recur. One entry per lesson.

## Architecture

- **Consumer-scoped processed cursors** (`processed_items(consumer, item_id)`), keyed on
  the dedup survivor (`canonical_item_id`). One consumer marking an item processed must
  never blind another. This is what makes "reusable across the ecosystem" actually true.
  (Origin: cross-model design review, 2026-06-02.)
- **Keep the `mcp` SDK out of the library import path.** `mcp_server.py` imports `api.py`,
  never the reverse — so `from aib_reader import ...` (the cron path) stays MCP-free.

## Pitfalls (anticipated, from the design review)

- **303 real feeds do NOT "scale for free."** Expect malformed XML, dead URLs, timezone
  bugs, and first-fetch floods of 200 historical items. Robustness (conditional GET,
  per-feed error isolation, flood cap, dead-feed deactivation) is v1 scope, not later.
