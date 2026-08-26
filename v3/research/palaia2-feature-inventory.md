# Research: palaia v2 feature inventory

**Purpose:** requirements baseline for v3. Every v2 capability gets a verdict:
does the *concept* survive into v3 (usually re-implemented, not ported), is it
reworked, or does it die. "Keep" never means "copy code" — v3 is a rewrite.

Source: `palaia/` @ v2.8.0 (~20k LOC Python, 75 test files, ~16k LOC tests) plus
`packages/openclaw-plugin/` (TypeScript). See `ARCHITECTURE.md` (root) for module map.

## Core storage & format

| v2 capability | Module(s) | Verdict for v3 | Rationale |
|---|---|---|---|
| Flat Markdown files as entry storage | `store.py`, `entry.py` | **Keep & strengthen** | Becomes a full human-readable vault (Obsidian/git); files are the source of truth |
| YAML frontmatter entry format | `frontmatter.py`, `entry.py` | **Keep, redesign schema** | Align with Obsidian conventions + knowledge-graph markup (see basic-memory dossier) |
| Entry types (memory/process/task) | `enums.py` | **Rework** | Type system worth keeping; exact taxonomy is a v3 design decision |
| SQLite backend + sqlite-vec | `backends/sqlite.py` | **Keep as *derived index*** | v3 inverts the relationship: DB is a rebuildable index over files, never primary data |
| PostgreSQL + pgvector backend | `backends/postgres.py` | **Drop (initially)** | v3 is single-host-first; the index is local. Revisit only if a real scale need appears |
| Custom WAL protocol + advisory file locks | `wal.py`, `lock.py`, `locking.py`, `project_lock.py` | **Drop** | Existed because JSON indexes were primary data. With files-as-truth + SQLite's own WAL + rebuildable index, a hand-rolled WAL is unnecessary complexity (~4 modules) |
| Flat-file → DB migration | `backends/migrate.py`, `migrate.py` | **Replace** | v3 needs one good importer: v2 store → v3 vault (plus basic-memory importer) |

## Search & intelligence

| v2 capability | Module(s) | Verdict | Rationale |
|---|---|---|---|
| Hybrid search (0.4 BM25 + 0.6 vector) | `search.py`, `bm25.py` | **Keep concept** | Proven; exact weighting/engine re-decided in v3 (FTS5 vs. custom BM25) |
| Multi-provider embedding chain (6 providers) | `embeddings.py` | **Keep, simplify** | Provider chain is good; default must stay zero-config local (fastembed-class) |
| Embed server (daemon keeps model in RAM) | `embed_server.py`, `embed_client.py` | **Obsolete by architecture** | v2 needed it because the CLI was short-lived. v3 is a long-running daemon — the model just stays loaded |
| Decay scoring + HOT/WARM/COLD tiering | `decay.py`, ADR-004 | **Rework** | Relevance decay is valuable for recall ranking & context budgets; physical tier *directories* conflict with a human-browsable vault (stable paths!). Score, don't move files |
| Significance scoring / auto-capture | `significance.py` | **Keep concept** | Auto-capture is a differentiator; becomes provider-agnostic (hook/skill-driven) |
| Dedup on write (hash) | `store.py` | **Keep** | Cheap and prevents agent memory spam |
| Knowledge curation (cluster/dedup KEEP-MERGE-DROP) | `curate.py` | **Later phase** | Good idea, not MVP |
| Adaptive agent coaching ("nudge") | `nudge.py`, `cli_nudge.py` | **Rework** | The goal (agents actually *use* memory) moves into skills/prompts + hooks |

## Multi-agent

| v2 capability | Module(s) | Verdict | Rationale |
|---|---|---|---|
| Scopes: private/team/public | `scope.py`, ADR-002 | **Keep, generalize** | Becomes scopes across *providers/clients*, enforced by the hub, not by convention |
| Agent identity & aliases, `--isolated` | `config.py`, tests | **Keep, generalize** | Identity moves to hub-issued tokens (auth layer) instead of CLI flags |
| Inter-agent memos | `memo.py`, ADR-010 | **Superseded** | Replaced by the v3 Messenger (session directory + structured messages) |
| Projects (per-project knowledge) | `project.py`, ADR-008 | **Keep** | Maps to vault folders/projects; also the unit for scoping and toolsets |
| Injection priorities per agent/project | `priorities.py` | **Rework** | Becomes context-budget policy in the recall API |

## Integrations & operations

| v2 capability | Module(s) | Verdict | Rationale |
|---|---|---|---|
| MCP server (stdio) | `mcp/server.py` | **Replace** | v3's MCP endpoint is the *primary* interface (HTTP + OAuth), not an add-on |
| OpenClaw plugin (ContextEngine, 7 hooks) | `packages/openclaw-plugin/` | **Demote to adapter** | OpenClaw becomes one client among many; v2 plugin keeps serving v2 users |
| CLI (argparse, ~1.5s cold start) | `cli*.py` | **Demote** | v3 is UI-first + API-first; a thin CLI remains for admins/CI, not the main surface |
| Doctor (checks/fixes/detection) | `doctor/` | **Keep, elevate** | Self-diagnosis with auto-fix is core UX ("everything automatic"); becomes a dashboard feature with one-click fixes |
| WebUI memory explorer (FastAPI, localhost) | `web/`, `ui.py` | **Superseded** | v3's dashboard is the product's face, not a viewer bolted on |
| Document ingestion / RAG | `ingest.py`, ADR-009 | **Later phase** | Useful, not MVP; add-on candidate |
| Knowledge packages export/import | `packages.py`, `sync.py` | **Rework** | Becomes vault sub-tree export + git-based exchange (ADR-005 idea generalizes) |
| Upgrade command (self-update) | `cli` | **Keep, elevate** | One-click update in dashboard, HA-style |
| ClawHub skill distribution | `SKILL.md` ×3 copies | **Rework** | v2's 6-file version-sync pain must die; v3 generates client artifacts from one source |

## v2 pain points v3 must not repeat

1. **Version sprawl:** 6 files must agree on the version (CONTRIBUTING lists them). v3: one version source, everything else generated.
2. **Cold-start tax:** every CLI call paid init cost; the embed-server daemon was a workaround. v3: one resident service.
3. **Index-as-truth fragility:** custom WAL + locking existed to protect derived JSON state. v3: files are truth, index is disposable.
4. **Per-client setup burden:** each MCP client is configured by hand. v3's whole point: configure the hub once.
5. **Tier directories move files:** breaks stable links/paths for humans and git history. v3: logical tiering via scores.
6. **OpenClaw coupling:** deep host-specific plugin. v3: provider-neutral core, thin adapters.
