# Research: basic-memory — concept dossier

**Purpose:** ground v3's memory design in what basic-memory got right and wrong.
**Method:** full-repo analysis of https://github.com/basicmachines-co/basic-memory
at commit `4d1dfdb` (v0.23 in progress), 2026-08-22. All claims path-cited.
**License caution:** basic-memory is **AGPL-3.0** with a copyright-assignment CLA
(single-vendor dual licensing). v3 adopts *concepts only*, clean-room — see
[ADR-002](../decisions/002-clean-room-licensing.md).

## 1. Knowledge model (the crown jewel)

Grammar: **Entity → Observations + Relations, encoded entirely in plain Markdown**
(`NOTE-FORMAT.md`).

- **Entity** = one file. Markdown gets frontmatter + parsed semantics; non-markdown
  files are still indexed as entities.
- **Frontmatter**: `title`, `type` (default `note`), `tags`, `permalink` (stable slug,
  survives file moves), optional `schema`, `created`/`modified`. Arbitrary custom keys
  are allowed and searchable as metadata.
- **Observations**: list items `- [category] content #tag1 #tag2 (context)`. Long tail
  of exclusion heuristics needed (checkboxes, callouts, timestamps, links) — the
  grammar was never formally specified, only patched.
- **Relations**: `- relation_type [[Target]] (context)`; bare `[[X]]` anywhere in
  prose becomes implicit `links_to`. Relation types are open vocabulary.
- **Forward references**: relations may target entities that don't exist yet;
  auto-resolved when the target appears — no full reindex.
- **`memory://` URLs** with glob patterns; `build_context` traverses the graph with
  depth/timeframe — memory as a *navigable API*, not a search box.
- **Synthetic permalinks** make individual observations/relations addressable in
  search results.
- **Picoschema**: optional per-type schemas (themselves stored as notes), validation
  `warn` by default, schema *inference* from usage frequency and drift detection.
  Structure emerges instead of being imposed. (Concept originates from Google
  Dotprompt, Apache-licensed.)

## 2. Storage & sync

- **Files are product truth; DB is a derived projection** — SQLite (WAL) or Postgres,
  SQLAlchemy + 27 Alembic migrations, one DB for all projects (`project_id` scoping).
- File watching via `watchfiles` with debounce + gitignore filtering; full rebuild
  compares checksums; **move detection by checksum match**; `bm doctor` verifies
  file↔DB consistency; `bm reindex` restores everything from disk.
- **Wart:** local MCP writes are DB-first — accepted into the DB, `202`, file
  materialized *asynchronously* (`mcp/server.py:196-200`). Crash window + conceptual
  dilution of "files are truth". v3: synchronous write-through for local mode.
- **Concurrency:** checksum write guards + generation-versioned compare-and-swap
  (v0.23) made concurrent agents *safe* — but not *aware* (no identity, no leases,
  last-accepted-wins).
- **No git anywhere in the engine.** Cross-device sync is "use git/Syncthing
  yourself"; version history exists only in their paid cloud (snapshots).

## 3. Search

- FTS5 (SQLite) / tsvector (Postgres) over entities *and* observations *and*
  relations in one index; boolean operators, metadata/type/date filters.
- Vectors: FastEmbed local ONNX by default (`bge-small-en-v1.5`), LiteLLM/OpenAI
  optional; pluggable indexes: sqlite-vec, pgvector, Milvus.
- Modes `fts | vector | hybrid` + opt-in cross-encoder reranking (local tiny-reranker
  or hosted). Retrieval debugging (`bm inspect query`) is a nice operability touch.

## 4. MCP server

- **FastMCP 4.0.0b1 + MCP SDK v2** pinned (beta-pin = churn risk they accepted).
- ~20 tools: write/read/edit/move/delete note, search, `recent_activity`,
  `build_context`, project management, schema tools, ChatGPT-compat `search`/`fetch`
  (gated by client-info middleware). An MCP-UI experiment exists but is disabled.
- **Tool ergonomics worth stealing:** MCP behavior annotations
  (`readOnlyHint`/`destructiveHint`/…) on every tool; pydantic `AliasChoices` absorb
  LLM parameter-name misses (`folder/dir/path`); dual `text|json` output; server
  `instructions` for cold-start orientation; an `ai_assistant_guide` resource served
  *to the model*.
- Transports: stdio, streamable-http, SSE — **local HTTP is explicitly
  unauthenticated** (docker-compose warns). Auth exists only cloud-side (WorkOS
  AuthKit, API keys).
- Internal shape: MCP tool → typed client → FastAPI HTTP API (in-process locally,
  remote in cloud) → service → repository. One API for local and cloud is what makes
  per-project cloud routing transparent — elegant.

## 5. Projects, Obsidian, distribution

- Multi-project: config-registered paths, env-var single-project lockdown, per-project
  `local|cloud` routing mode; cloud "workspaces" for teams.
- Obsidian compat = shared markdown dialect (wikilinks render in graph view, callouts
  excluded from parsing, `.obsidian/` ignored). Their only Obsidian-*write* feature
  (canvas generation) was removed in v0.23.
- Distribution: uv/pip/Homebrew, self-updating CLI, GHCR image, official MCP registry
  (`server.json`), Smithery, Glama, `llms-install.md` (agent-executed install!),
  Claude Code plugin + marketplace.json, Codex plugin, 15 SKILL.md skills, OpenClaw
  package. Importers: Claude, ChatGPT, memory-JSON, ZIP.
- Cloud: basicmemory.com $15/mo (WorkOS + Neon Postgres + Tigris S3, rclone bisync).
  Open-core tension is baked into the OSS: promo telemetry in the CLI (opt-out env
  var), cloud-shaped code paths throughout.

## 6. Confirmed gaps (v3's openings)

1. **No outbound eventing.** Nothing fires on entity change — no webhooks, no plugin
   hooks, no change feed. Automation requires polling. (Their `hooks/` dir is
   *inbound* only: harness lifecycle capture with a **promotion ladder**
   `raw → summarized → candidate → accepted` — "agents propose memory, they don't
   silently create it". The ladder itself is worth adopting.)
2. **No permission model.** Any connected client: full CRUD on all projects. No
   read-only mode, no scopes, no local auth.
3. **Thin multi-agent semantics.** Safe concurrency, zero awareness: no per-agent
   identity locally, no session views, no coordination.
4. **No git integration** despite a git-perfect format.
5. **Accidental complexity:** ~104k LOC src, 360 unit-test files (~146k LOC,
   5,181 tests, 100%-coverage policy), 27 migrations — much of it serving the cloud
   path. A local-first successor can be 10–20× smaller.
6. **Format by accretion:** the parsing grammar is regex-heuristic with patch-on-patch
   exclusions. v3 should specify its vault format formally and version it.

## 7. What v3 adopts / fixes (summary)

**Adopt (clean-room):** the Markdown grammar (entities/observations/relations/
wikilinks), files-as-truth + disposable index + checksum change detection + doctor,
`memory://` addressing + graph-traversal recall, synthetic sub-note addressability,
schema-as-notes with warn-first validation + inference, promotion ladder for
auto-capture, tool-ergonomics package (annotations, alias absorption, model-facing
guide resource), hybrid FTS+vector on embedded engines, one-API-for-local-and-remote.

**Fix:** outbound event bus + hooks (platform property), permission/scope model with
auth from day one, agent identity + session awareness, git-native versioning with
attributed auto-commits, synchronous local write-through, a formally specified and
versioned vault format, and a radically smaller core.

**Avoid:** AGPL code (ADR-002), beta-framework pins in release builds, cloud promos
inside the OSS, feature churn without deprecation paths.
