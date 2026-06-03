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

### Step 3 — v0.0b: the library (Approach B)  ✅ CODE COMPLETE (branch feat/v0.0b-library)
- [x] `store/sqlite` query/write methods (recent_items, search, mark_processed, upsert_feeds, ...)
      + schema migration for last_status/consecutive_failures/last_error
- [x] `fetcher` (bounded async httpx, conditional GET, per-feed isolation, UTC timestamps)
- [x] `dedup` survivor selection over the store (item_surrogate_id: canonical_url -> guid ->
      content_hash; exact via id-collision, fuzzy via assign_survivor)
- [x] `api.poll_feeds`, `api.add_feed`; `cli doctor` health + `--deactivate`
- [x] First-fetch flood cap (default 14 days)
- [x] Tests: 66 green (store/fetcher/poll over httpx.MockTransport), ruff clean
- [x] Dogfood: AI World slice → 104 items/3.5s; full 286-feed ingest → 208 polled /
      78 failed / 2604 items in **40s** (<5min gate ✓). Contract verified live:
      search, fetch_recent_items, consumer-scoped idempotent mark_processed.
- [ ] Robustness gate (a): transient-failure <15%/ingest sustained over 7 daily runs —
      ONGOING observation. Raw first-pass failure 27% is mostly permanently-dead feeds
      (404s/dead domains/Reddit api.reddit.com 403s); run `doctor --deactivate` to prune,
      then measure transient rate on active feeds.

### Step 4 — v0.0c: MCP server + register  ✅ CODE COMPLETE (branch feat/v0.0c-mcp)
- [x] 5 tools confirmed end-to-end (already wired to api); `tests/test_mcp_server.py`
      covers registry + 1:1 delegation + the recent_items arg reorder + JSON shapes
- [x] Registered user-scope via `claude mcp add -s user aib-reader` with an absolute
      venv console-script command + `AIB_READER_FEEDS_CONFIG` env override (fixes the
      relative-path/CWD fragility when launched as a background server). `claude mcp
      list` → ✓ Connected.
- [x] Stdio smoke test (`scripts/_mcp_smoke.py`): spawns the real server, initialize,
      lists 5 tools, recent_items(AI World/7d) + search_items(Anthropic) return real items.
- [x] Import isolation hardened: `test_library_import_does_not_pull_in_mcp_sdk` now
      asserts in a fresh subprocess (was order-dependent once a test imports the SDK).
- [ ] **Action for James:** restart Claude Code, then in a fresh session ask
      "What's been published about Anthropic this week?" → real items via the MCP tools.

### Step 5 — Integration handshake  ✅ COMPLETE (2026-06-03)
- [x] aib-pipeline now declares aib-reader as an editable uv **path dependency**
      (`[tool.uv.sources] aib-reader = { path = "../aib-reader", editable = true }`).
- [x] `aib_pipeline/source.py` seam wraps the contract (`fetch_recent_items` /
      `mark_processed` / `poll_feeds`), consumer pinned to `"aib-pipeline"`.
- [x] Zero-overhead verified from the consumer: importing `aib_pipeline.source` does
      NOT load the `mcp` SDK (asserted in a subprocess, both repos' test suites).
- [x] Live: the seam reads 100 real "AI World" items from the shared store; consumer-
      scoped `mark_processed` confirmed (aib-pipeline's marks don't hide items from
      other consumers).
- See `aib-pipeline/tasks/todo.md` (D7 superseded, OQ#5 resolved) and
  `aib-pipeline/tests/test_aib_reader_integration.py`.

---

## v1 milestone status

v0.0a (Horizon eval) → v0.0b (library) → v0.0c (MCP) → integration handshake are all
**done**. The contract `from aib_reader import fetch_recent_items, mark_processed` is
live, tested both sides, and consumed by aib-pipeline with zero MCP overhead. Remaining
open threads are operational, not build: the 7-run robustness-gate sample (daily launchd
job, evaluate ~2026-06-10) and pruning permanently-dead feeds via `doctor --deactivate`
once they cross the failure threshold.

## Review (filled in as milestones land)
- Step 0: _pending verification_
