# Feedly Replacement: Self-Hosted RSS Reader with API/MCP — Research Handoff

> **Purpose of this doc:** Hand-off brief for a Claude Code session. It captures the
> research, the decision, and a concrete implementation path so the next session can
> go straight to building. Read the whole thing once before acting; the "Next Actions"
> section is the executable part.
>
> **Status:** Research complete. Reader not yet selected (see Open Decisions). No
> infrastructure provisioned yet.
> **Last updated:** 2026-06-01

---

## 1. Objective

Replace Feedly as the RSS reader. The replacement must expose programmatic access via
a **REST API and/or an MCP server**, and should be **open source**. The end state is a
self-hosted reader wired into ClaudeClaw via MCP so agents can browse feeds, read/triage
entries, search, and manage read/star state.

## 2. Hard requirements (from the original ask)

- [x] API access OR an MCP server (REST API strongly preferred as the foundation).
- [x] Open source.
- [x] Must replace Feedly's reading workflow.
- [ ] Migrate existing **~269 feeds** (already exported as OPML).

## 3. Why this category solves the problem

Feedly gates its developer API behind its top enterprise tier. A **Pro+** subscription
does **not** include API access — this is the blocker that triggered the search. A
self-hosted, open-source reader removes the gate entirely: you own the instance, so the
API is always available with no tier to buy and no externally imposed rate limits. OPML
export is available from Feedly even on lower tiers, so feed migration is unaffected by
the API lockout.

## 4. Decision: two frontrunners

Both **Miniflux** and **FreshRSS** satisfy every hard requirement. Pick one:

- **Choose Miniflux** if the priority is the cleanest programmatic/agentic control with
  the least operational friction. Native REST API is pleasant to script; richest MCP
  ecosystem; single Go binary is trivial in Docker. Tradeoff: opinionated minimalism
  (limited theming, shallow folder nesting).
- **Choose FreshRSS** if the priority is feature coverage — especially **built-in XPath/JSON
  web scraping** for sources that publish **no feed at all** (directly useful for Resist
  and Rise investigative tracking). Uses the Google Reader API standard, which also unlocks
  the widest ecosystem of polished mobile/desktop client apps.

Either choice fully ends the Feedly API problem. A hedge: run whichever reader you prefer,
then optionally point the generic Google Reader-compatible MCP server at it so you are not
locked to a single implementation's toolset.

## 5. Comparison

| Dimension | Miniflux | FreshRSS |
|---|---|---|
| License | GPLv3 (Affero) | AGPL-3.0 |
| Stack | Single Go binary + Postgres | PHP + DB (MySQL/MariaDB/Postgres/SQLite) |
| API style | Clean native REST API | Google Reader API (full) + Fever API (limited) |
| MCP servers | Multiple, incl. 40+ tool server & an OpenClaw Rust build | Multiple, incl. a token-optimized OpenClaw-bridge build |
| Web scraping (no-feed sites) | Limited (rewrite rules) | Built-in XPath + JSON scraping |
| Client app ecosystem | Native API + GReader/Fever compatibility | Broad (GReader standard: Reeder, FocusReader, etc.) |
| Philosophy | Opinionated minimalism | Feature-rich, configurable |
| Hosting | Free self-hosted; ~$1/mo on PikaPods | Free self-hosted |

## 6. MCP server inventory (actionable repo list)

### Miniflux
- **tssujt/miniflux-mcp** — 40+ tools covering all Miniflux API functionality (feeds,
  entries, users, categories). API-key or username/password auth. MIT.
  `https://github.com/tssujt/miniflux-mcp`
- **tan-yong-sheng/miniflux-mcp** — read-only server; npm-published, runnable via `npx`.
  `https://github.com/tan-yong-sheng/miniflux-mcp`
- **openclaw-miniflux-mcp** (Rust, ~Mar 2026) — 13 read + 3 write tools, ships an OpenClaw
  skill that teaches agents tool usage. Relevant given OpenClaw → ClaudeClaw lineage.
  `https://lib.rs/crates/openclaw-miniflux-mcp`

### FreshRSS
- **ChrisLAS/freshrss-mcp** — wraps the FreshRSS Google Reader API; Streamable HTTP
  transport; built for the OpenClaw gateway via openclaw-mcp-bridge. **Token-optimized:
  returns only essential fields with configurable summary truncation (~90% reduction vs
  raw RSS XML)** — important for piping 269 feeds into LLM context. Ships a NixOS module.
  `https://github.com/ChrisLAS/freshrss-mcp`
- **jeromewoody/freshrss-mcp** — Python/FastMCP; browse, read, search, subscribe,
  mark read/unread, star.
  `https://github.com/jeromewoody/freshrss-mcp`
- **ivanlee1999/freshrss-mcp** — Python; stdio + streamable HTTP transports; 13 tools.
  `https://github.com/ivanlee1999/freshrss-mcp`

### Implementation-agnostic
- **xueli-sherryli RSS Reader (Google Reader API) MCP** — works with any Google
  Reader-compatible service (FreshRSS, TT-RSS); subscriptions, folders, tagging, bulk ops.
  `https://www.pulsemcp.com/servers/xueli-sherryli-rss-reader`

## 7. Next actions (executable in Claude Code)

> Target host: Mac Studio (Docker available) or a small VPS. Pick the reader from
> Open Decisions first, then run the matching path.

### Path A — Miniflux (recommended default)

1. Stand up Miniflux + Postgres via Docker Compose. Starter compose:

   ```yaml
   services:
     miniflux:
       image: miniflux/miniflux:latest
       ports:
         - "8080:8080"
       depends_on:
         db:
           condition: service_healthy
       environment:
         - DATABASE_URL=postgres://miniflux:CHANGE_ME@db/miniflux?sslmode=disable
         - RUN_MIGRATIONS=1
         - CREATE_ADMIN=1
         - ADMIN_USERNAME=admin
         - ADMIN_PASSWORD=CHANGE_ME
     db:
       image: postgres:16
       environment:
         - POSTGRES_USER=miniflux
         - POSTGRES_PASSWORD=CHANGE_ME
       volumes:
         - miniflux-db:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD", "pg_isready", "-U", "miniflux"]
         interval: 10s
         start_period: 30s
   volumes:
     miniflux-db:
   ```
   (Do not commit real secrets — use an `.env` file or the secrets store, not inline values.)

2. Log into the web UI, then create an API key: **Settings → API Keys → Create**.
3. Import the OPML (Settings → Import) — this completes the feed migration.
4. Wire MCP into ClaudeClaw. Example (npm `npx` server):

   ```json
   {
     "mcpServers": {
       "miniflux": {
         "command": "npx",
         "args": ["-y", "miniflux-mcp"],
         "env": {
           "MINIFLUX_BASE_URL": "http://localhost:8080",
           "MINIFLUX_TOKEN": "<API_TOKEN>"
         }
       }
     }
   }
   ```
   Or the Rust OpenClaw build (note different env var names + optional read-only flag):

   ```json
   {
     "mcpServers": {
       "miniflux": {
         "command": "/path/to/openclaw-miniflux-mcp",
         "args": ["--read-only"],
         "env": {
           "MINIFLUX_URL": "http://localhost:8080",
           "MINIFLUX_API_TOKEN": "<API_TOKEN>"
         }
       }
     }
   }
   ```

### Path B — FreshRSS

1. Deploy FreshRSS via its official Docker image (`freshrss/freshrss`) + a DB.
2. Enable the API: **Settings → Authentication → Allow API access**, and set the dedicated
   **API password** (this is separate from the login password — the MCP servers want the
   API password).
3. Import the OPML.
4. Wire MCP. Example (jeromewoody Python server) — uses the Google Reader API:

   ```json
   {
     "mcpServers": {
       "freshrss": {
         "command": "freshrss-mcp",
         "env": {
           "FRESHRSS_URL": "https://freshrss.example.com",
           "FRESHRSS_EMAIL": "<username>",
           "FRESHRSS_API_PASSWORD": "<api_password>"
         }
       }
     }
   }
   ```
   For the token-optimized ChrisLAS server, prefer it if context-window cost is a concern;
   it runs over Streamable HTTP and has a NixOS module for a hardened systemd service.

### Both paths
- Put the reader behind a reverse proxy (Caddy/nginx) with TLS before exposing beyond localhost.
- Keep MCP tokens in the secrets store, never in committed config.
- Validate end-to-end: list subscriptions → fetch unread for one feed → mark read → confirm
  state change via the web UI.

## 8. Open decisions (need user input)

1. **Reader choice:** Miniflux (clean API, minimal) vs FreshRSS (scraping, GReader ecosystem)?
   - Tie-breaker question: are there R&R sources with **no RSS feed** that need scraping? If
     yes, that pushes toward FreshRSS.
2. **Host:** Mac Studio (local, always-on?) vs VPS/PikaPods (remote, ~$1/mo)?
3. **MCP transport:** stdio (local, simplest) vs Streamable HTTP (works with the OpenClaw/ClaudeClaw gateway).
4. **Read-only vs read-write** for the agent's first integration (recommend starting read-only).

## 9. ASTGL content hook

This is a clean "replace a SaaS lock-in with self-hosted + MCP" story for the ASTGL pipeline:
the Feedly Pro+ API lockout as the pain point, the self-hosted pivot, and wiring an MCP server
into an agent workflow. Capture friction points during the build (OPML import gotchas, API
password vs login password confusion on FreshRSS, MCP token wiring, context-window cost and how
the token-optimized server addresses it).

## 10. Sources

- Miniflux MCP (tssujt) — github.com/tssujt/miniflux-mcp
- Miniflux MCP read-only (tan-yong-sheng) — github.com/tan-yong-sheng/miniflux-mcp
- openclaw-miniflux-mcp (Rust) — lib.rs/crates/openclaw-miniflux-mcp
- Miniflux self-hosting writeup — christiano.dev/post/self_hosted_rss
- Miniflux setup + PikaPods pricing — noted.lol/miniflux
- FreshRSS GitHub (API + scraping) — github.com/FreshRSS/FreshRSS
- FreshRSS Google Reader API docs — freshrss.github.io/FreshRSS
- FreshRSS MCP token-optimized / OpenClaw bridge (ChrisLAS) — github.com/ChrisLAS/freshrss-mcp
- FreshRSS MCP (jeromewoody) — github.com/jeromewoody/freshrss-mcp
- FreshRSS MCP (ivanlee1999) — github.com/ivanlee1999/freshrss-mcp
- Generic Google Reader API MCP (xueli-sherryli) — pulsemcp.com/servers/xueli-sherryli-rss-reader
- Self-hosted reader roundups — medevel.com/10-self-hosted-rss-feed, opensource.com/article/17/3/rss-feed-readers
- Tiny Tiny RSS — tt-rss.org
