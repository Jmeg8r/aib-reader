# Horizon Foundation Evaluation (v0.0a)

**Date:** 2026-06-02
**Question:** For `aib-reader`'s aggregation core, do we **adopt** Thysrael/Horizon as a
dependency, **fork** it, or use it as a **reference** and build from scratch?
**Verdict:** **REFERENCE.** Build the from-scratch SQLite core (Approach B); port a few of
Horizon's design ideas; do not adopt or fork it.

This artifact records the decision and the concrete evidence behind it — from reading the
source *and* running it against five of James's real feeds. Per the design doc, the goal is
to make this decision stick so it isn't re-litigated at 11pm three weeks from now.

---

## What I evaluated

Cloned `Thysrael/Horizon` (MIT, Python 3.11+, ~5.4k★, last commit 2026-06-02 — actively
maintained) to `/tmp/horizon-eval`. Read the orchestrator, RSS scraper, storage manager, and
models. Then ran Horizon's **own** RSS scraper against 5 real "AI World" feeds from the Feedly
OPML, with no API key.

### What I saw when I ran it

```
TOTAL fetched (last 60d, no API key): 80
   20  Google AI/ML
   32  Hugging Face Blog
   27  MIT News AI
    1  Ollama
Error fetching RSS feed OpenAI News: Client error '404 Not Found' for 'https://openai.com/feed.xml'
```

Three things that decided this, all observed (not theorized):

1. **The fetch stage works fine with no key** — `RSSScraper.fetch()` returned 80 items. But
   every item's `ai_score` and `ai_summary` came back `None`. **Horizon's value is produced
   entirely by the AI pipeline that runs *after* fetch** (`orchestrator.run()` steps 4-7:
   AI-score → filter by score → AI topic-dedup → AI-enrich → AI-summary), and that requires an
   LLM API key. The part we'd actually reuse (fetch) is the small, easy part.
2. **A real feed (OpenAI) 404'd, and Horizon swallowed it** — logged a warning, continued,
   and kept no record. There is no dead-feed tracking, no `doctor`, no deactivation. This is
   exactly the "303 feeds don't scale for free" risk made concrete on feed #3 of 5, and
   exactly the gap our `feeds.active` + `doctor` close.
3. **Item ids are `rss:{feed}:{sha16}`** — a per-feed hash, not a canonical URL. Cross-source
   dedup happens later, in-memory, by a simpler URL-normalization than ours.

---

## The disqualifier for ADOPT: there is no queryable item store

`StorageManager` (read in full) persists exactly three things: `config.json`, **daily summary
markdown** (`data/summaries/horizon-<date>-<lang>.md`), and a `subscribers.json`. That's it.

**There is no items table, no search, no per-item state, and no consumer cursors.** Items
live in memory for the duration of one `run()` and are then discarded; only the rendered
markdown summary survives. Horizon is a stateless daily *summarizer*, not a queryable
aggregation store.

Our entire contract — `fetch_recent_items(since, limit, category)`, `search_items`, and
**consumer-scoped** `mark_processed` over a persistent store — has no equivalent in Horizon.
Adopting it would mean importing a library that cannot answer a single one of our five MCP
tools, then building the store/query/cursor layer anyway. The embeddable subset Horizon does
expose (`fetch_all_sources` + `merge_cross_source_duplicates`, both marked "stable stage entry
point") is roughly a fetch loop plus a naive URL merge — ~50-80 lines we control better
ourselves, against a `Store` interface we can later swap for Miniflux.

Adoption also drags in `anthropic` + `openai` + `google-genai` + `ddgs` + `beautifulsoup4`
for an AI-scoring/enrichment pipeline that is **explicitly out of scope** for aib-reader
(editorial judgment is aib-pipeline's job). And `ContentItem` itself bakes `ai_score`,
`ai_summary`, and `ai_tags` into the model — the data shape is AI-scoring-oriented, not a
neutral aggregation item.

## The disqualifier for FORK

Forking means owning Horizon's seven-scraper zoo (GitHub, HN, Reddit, Telegram, Twitter,
OpenBB, OSSInsight) and its multi-provider AI pipeline, then deleting ~70% of it and bolting
on the persistent store + cursors it lacks. That is more work than building our focused core,
and it starts us from the wrong architecture (store-less, AI-coupled, CLI-first, v0.1.0
unstable API) instead of the right one.

## Why REFERENCE wins

Horizon is genuinely good and validates our stack (feedparser + httpx + pydantic +
python-dateutil + the `mcp` SDK — the same core we chose). We port the *ideas*, not the code:

- **RSS date-parsing fallback chain** — try `published` → `updated` → `created`, structured
  `*_parsed` first then string parsing, normalized to UTC (`rss.py:_parse_date`). Good model
  for our fetcher; we add the `published_at → fetched_at` null fallback Horizon lacks.
- **Per-feed error isolation** — one bad feed never aborts the batch (`rss.py` try/except).
  We keep this and *add* the missing piece: record the failure so `doctor` can deactivate
  dead feeds.
- **URL-normalization dedup** — `merge_cross_source_duplicates` strips `www`/trailing-slash/
  fragment. We extend it with tracking-param stripping + query sorting + a `canonical_item_id`
  survivor and a persistent store (Horizon's is in-memory, per-run).

What Horizon does NOT give us, and we therefore build: the SQLite store, category/time/keyword
queries, consumer-scoped processed cursors, conditional GET (ETag/Last-Modified — Horizon
re-downloads every feed every run), first-fetch flood capping, and the `doctor` health command.

---

## 3-way comparison (against the integration contract)

| Criterion | From-scratch SQLite (CHOSEN) | Miniflux/FreshRSS backend | Horizon adopt/fork |
|---|---|---|---|
| Satisfies `fetch_recent_items`/`mark_processed` contract | Directly | Via a REST adapter | No — no queryable store |
| Consumer-scoped cursors | Built in | We add them | Absent |
| Persistent queryable item store | SQLite | Postgres/SQLite (theirs) | **None** (summaries only) |
| Zero-overhead library import (4am cron) | Yes | localhost HTTP | N/A |
| Embeddable (UpdateKit imports it, no infra) | Yes | No (needs a container) | No |
| Pulls in unused/AI deps | No | No | Yes (4 LLM SDKs + scrapers) |
| License | MIT (ours) | GPLv3 / AGPL | MIT |
| Net | Matches the contract exactly; bounded build | Strong store, but a running service + not embeddable | Wrong architecture for this contract |

**Miniflux stays a live option as a future `Store` backend** — the swappable interface exists
precisely so a Miniflux-backed implementation can slot in if/when the personal-reading UX (the
handoff doc's goal) justifies a container. It is not reversed, just deferred.

## Decision

**REFERENCE.** Proceed to v0.0b building the from-scratch SQLite core (Approach B), porting
Horizon's date-parsing chain, per-feed isolation, and URL-normalization ideas, and adding the
store/query/cursor/conditional-GET/doctor layer Horizon does not have. This is confirmed by
both reading the source and running it.
