---
id: SPEC-106
title: Recall, graph traversal, context assembly
phase: 1
depends_on: [SPEC-104, SPEC-105]
model: opus-5
effort: high
status: draft
---

# SPEC-106: Recall, graph traversal, context assembly

## Goal
The intelligence on top of search: `memory://` resolution, graph traversal,
decay-scored ranking and token-budget-aware context assembly — the reason
agents *use* palaia instead of grepping files.

## Deliverables
1. `memory://` resolver per format spec (permalink, title/path fallback, glob
   patterns, sub-note permalinks).
2. `build_context` tool: start from a `memory://` ref or query, walk relations
   with depth + timeframe limits, return a deduplicated, budgeted context
   package (max_tokens param; entities summarized as title+key observations
   when over budget, never silently truncated mid-note).
3. **Decay-scored ranking**: recency/access/significance scoring (v2's proven
   concept, logical only — no file moves); scoring weights in config;
   deterministic given equal inputs.
4. **Per-model variants** (format spec + mcp-hub heritage): `recall` resolves
   `[category | model-scope]` observation variants to the single most specific
   one for the calling model; contract as pure function + table-driven tests.
5. Wire into SPEC-105 as `recall` + `build_context` tools with the ergonomics
   rules.

## Acceptance criteria
- [ ] traversal respects depth/timeframe and never loops on cyclic relations
- [ ] budget property test: assembled context ≤ max_tokens for random vaults,
      while never returning zero results when matches exist
- [ ] variant resolution table tests: exact model > family > default; unknown
      model → default; no variant → base observation
- [ ] ranking regression battery on the golden vault (expected top-3 per query
      checked in as fixtures)
- [ ] e2e: Claude Code asks "continue where we left off"-style query and gets
      the seeded context (SPEC-113 scenario)

## Non-goals
Auto-capture, curator, per-client injection policies (Phase 2).

## Model note
**Opus 5 / high** + **Fable 5 review** — ranking and budgeting decisions shape
whether palaia feels smart; regressions here are silent quality loss.
