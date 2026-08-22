# Research: palaia v2 vs. basic-memory — memory-system design comparison

**Purpose:** the explicit side-by-side that grounds v3's memory design (MASTERPLAN
§5.1) and feeds SPEC-004. Sources: `palaia2-feature-inventory.md`,
`basic-memory.md` (both in this directory), the mcp-hub prototype learnings
(private dossier), plus `ARCHITECTURE.md` (repo root, v2).
Licensing reminder: basic-memory concepts are adopted clean-room only (ADR-002);
palaia v2 and mcp-hub are ours — code reuse allowed where it fits.

## Decision matrix

| # | Dimension | palaia v2 | basic-memory | v3 decision & rationale |
|---|---|---|---|---|
| 1 | Source of truth | Files + derived JSON/SQLite indexes, but indexes carry state a custom WAL must protect | Files are truth, DB is a projection — yet local MCP writes are DB-first (202 + async file materialization) | **Files are the only truth, synchronous write-through, index fully disposable.** bm's model, minus its async wart; kills v2's WAL/locking complexity (4 modules) |
| 2 | Entry format | YAML frontmatter + free markdown body; fixed type enum (memory/process/task) | Frontmatter + semantic grammar: observations `- [category] text #tag`, typed relations, custom keys | **bm's grammar, formally specified (EBNF) and versioned** (bm grew by patch-on-patch heuristics); v2's typed-entry discipline survives as the taxonomy (SPEC-004) |
| 3 | Knowledge graph | None — tags, scopes and projects only | Entities/observations/relations, wikilinks, forward references, resolved lazily | **Adopt bm's model wholesale** — it is the crown jewel; v2 had nothing comparable |
| 4 | Addressing | UUID file paths | `memory://` permalinks, stable across moves; synthetic sub-note permalinks | **Adopt bm's addressing** — stable, human-legible, sub-note-granular |
| 5 | Search | Hybrid 0.4·BM25 + 0.6·vector; 6 embedding providers; separate embed-server daemon | FTS5 + fastembed local default + pluggable vector indexes; opt-in reranking | **Merge:** hybrid (v2's proven weighting as starting point) on FTS5 + sqlite-vec (bm's engine choice); no embed-server (v3 is a daemon — v2's workaround is obsolete); reranking later |
| 6 | Recall & ranking | Decay scoring + HOT/WARM/COLD **physical** tiers; token-budget context assembly (plugin) | `recent_activity` timeframes + `build_context` graph traversal; no decay model | **The genuine merge point:** v2's decay scoring (logical only — physical tiers lose to stable paths/git history) + bm's graph traversal + v2's budgeted assembly. Neither system has all three; v3 does (SPEC-106) |
| 7 | Capture | Auto-capture with significance scoring + hash dedup, but writes land directly | Inbound hook WAL with promotion ladder (raw→candidate→accepted); no curator in OSS core | **Inbox + curator (mcp-hub, proven in production)** = the ladder with an active brain; v2's significance/dedup guard the inbox entrance (SPEC-107, Phase-2 curator) |
| 8 | Curation | `curate.py`: ML clustering, KEEP/MERGE/DROP — batch, no LLM | None locally (cloud feature) | **LLM curator job** with the mcp-hub two-tier rule (INGEST autonomous / MAINTENANCE only as reviewed proposal), deterministic apply — beyond both predecessors |
| 9 | Multi-agent | Scopes private/team/public, agent identity + aliases, `--isolated`, project locks | None locally: every client full CRUD; safety-level concurrency only (checksum guards, CAS) | **v2 wins and generalizes:** scopes enforced by hub tokens per client/vault; bm contributes the write-safety mechanics (checksum conflicts) |
| 10 | Multi-store | Projects inside one store | Multiple projects, one shared DB, env-var lockdown | **User's choice: one vault with scopes or many physically isolated vaults**, each its own storage/git/tool family (owner requirement; bm's shared-DB model rejected for isolation) |
| 11 | Crash safety & concurrency | Custom WAL protocol + fcntl advisory locks (existed to protect derived state) | SQLite WAL + checksum write guards + generation CAS | **Atomic writes (tmp+fsync+rename) + git + rebuildable index + checksum conflict errors.** No custom WAL (nothing derived is precious), no lock files |
| 12 | History / versioning | None (WAL = recovery, not history) | None in OSS (snapshots = paid cloud) | **Git-native: attributed auto-commits, browsable history, Obsidian-git compatible.** v3's differentiator — both predecessors lack it |
| 13 | Human access | Read-mostly WebUI (localhost) | Obsidian coexistence (shared markdown dialect) | **Both:** Obsidian+git as the power path, dashboard explorer as the default path |
| 14 | Events / hooks | None | None outbound (inbound harness hooks only) | **First-class event bus + hooks (MASTERPLAN §5.6)** — the gap both share, and palaia's automation pillar |
| 15 | MCP tool ergonomics | 3 basic tools (search/get/write) | Annotations, alias absorption, dual output, model-facing guide resource | **Adopt bm's ergonomics package** + palaia's naming rules (vault identity in tool names, user-renamable) which neither has |
| 16 | Structure / schemas | Fixed enums in code | Picoschema: schemas-as-notes, warn-first, inference from usage | **bm's approach in Phase 2+** — structure emerges, never imposed; v2's rigidity rejected |
| 17 | Footprint | ~20k LOC, zero hard deps for core | ~104k LOC, 27 migrations, cloud-shaped paths | **v2's size discipline with bm's ideas:** local-first successor targeted at a fraction of bm's LOC |
| 18 | Migration | (n/a — v2 is a source) | Importers for Claude/ChatGPT/JSON | **Importers for both v2 stores and bm vaults** (SPEC-111) |

## Where the two disagree — and who won

1. **Physical tiers (v2) vs. stable paths (bm):** bm wins. Moving files between
   hot/warm/cold breaks links, git history and human orientation. v2's *insight*
   (relevance decays) survives as a ranking signal, not a filesystem layout.
2. **Custom WAL (v2) vs. files-as-truth (bm):** bm wins. v2's hardest code existed
   only because derived state was precious. Make the index disposable and the
   problem deletes itself.
3. **Scopes (v2) vs. open access (bm):** v2 wins. bm's "any client, full CRUD" is
   untenable for a multi-provider hub; v2's scope model generalizes into the
   token/permission layer.
4. **Semantic grammar (bm) vs. free-form body (v2):** bm wins — but only with a
   formal, versioned grammar; bm's own accretion-by-regex history is the warning.
5. **Direct auto-capture (v2) vs. propose-then-promote (bm/mcp-hub):** the ladder
   wins, upgraded by mcp-hub's curator; v2's significance scoring survives as the
   inbox's noise gate.
6. **Where neither had an answer** (v3 must invent): git-native history, outbound
   events/hooks, per-model recall variants (mcp-hub), vault-carrying tool names,
   token-budgeted graph recall combining decay + traversal.

## Feeding SPEC-004

The format spec inherits directly: grammar per #2/#3/#4 (formal, versioned),
frontmatter with v2-style types as a *starting* taxonomy, reserved folders from
the inbox/curator flow (#7/#8), stable-path rule from #1 (no tier directories),
and the conformance-corpus obligation from bm's cautionary tale.
