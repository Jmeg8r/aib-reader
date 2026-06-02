# aib-reader — Implementation Plan

**Project:** Self-owned RSS aggregation substrate for the ASTGL ecosystem.
**Status:** v0.0 — scaffold in progress.
**Design doc (source of truth):** `~/.gstack/projects/aib-reader/jamescruce-main-design-20260602-000217.md`

## Locked decisions

- Library-first (importable, zero-overhead) + thin local-stdio MCP wrapper.
- v1 = aggregation-query only. All OPML feeds ingested; category is first-class.
- From-scratch SQLite behind a swappable `Store` interface (Miniflux drop-in later).
- Approach B (robustness-first). Reference Horizon; defer AI scoring to aib-pipeline.
- Contract: `from aib_reader import fetch_recent_items, mark_processed` (+ pydantic `Item`),
  consumer-scoped cursors. Every MCP tool maps 1:1 to a library function.

## Build sequence

### Step 0 — Scaffold  (in progress)
- [x] git init (main) + `chore/scaffold` branch
- [x] `.gitignore` (secrets first), `pyproject.toml`, `.env.example`, README, CLAUDE.md
- [x] Package skeleton: models, _logging, config, _time, dedup, store/(protocol+sqlite),
      fetcher, opml, api, cli, mcp_server
- [x] Real now: models, logging, config, `parse_since`, `canonical_url`/`content_hash`,
      SQLite schema, CLI `doctor`
- [x] Tests (time, dedup, smoke) green
- [x] Verify: `uv run aib-reader --help`, `uv run aib-reader doctor`, `uv run pytest` (32 passed)

### Step 1 — v0.0a: Horizon foundation evaluation  ✅ VERDICT: REFERENCE
- [x] Clone Thysrael/Horizon to /tmp/horizon-eval; read source; run vs 5 real feeds (80 items, no key)
- [x] Write `docs/horizon-evaluation.md` (3-way verdict; concrete reason adoption rejected)
- Key finding: Horizon has NO queryable item store (saves daily summary markdown only) and no
  consumer cursors — our entire contract has no equivalent. Value is AI-pipeline-coupled. Port
  its date-parsing/per-feed-isolation/URL-normalization ideas; build the store ourselves.

### Step 2 — v0.0b prep: feeds.yaml from OPML
- [ ] Implement `opml.parse_opml` + `opml.opml_to_feeds_yaml`
- [ ] Generate `config/feeds.yaml` from the Feedly export (all feeds, categories, AI slice tagged)

### Step 3 — v0.0b: the library (Approach B)
- [ ] `store/sqlite` query/write methods (recent_items, search, mark_processed, upsert_feeds, ...)
- [ ] `fetcher` (bounded async httpx, conditional GET, per-feed isolation, UTC timestamps)
- [ ] `dedup` survivor selection over the store (canonical_url -> content_hash -> fuzzy)
- [ ] `api.poll_feeds`, `api.add_feed`
- [ ] First-fetch flood cap (default 14 days)
- [ ] Robustness gate: transient-failure <15%/ingest, doctor deactivates dead feeds, ingest <5 min

### Step 4 — v0.0c: MCP server + register
- [ ] Confirm the 5 tools work end-to-end (already wired to api)
- [ ] Register user-scope in ~/.claude.json; smoke test from a fresh session

### Step 5 — Integration handshake
- [ ] Add aib-reader to aib-pipeline as a uv path dependency; verify zero-overhead contract

## Review (filled in as milestones land)
- Step 0: _pending verification_
