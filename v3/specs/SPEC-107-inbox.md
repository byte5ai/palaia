---
id: SPEC-107
title: Inbox & capture contract
phase: 1
depends_on: [SPEC-105]
model: sonnet-5
effort: medium
status: draft
---

# SPEC-107: Inbox & capture contract

## Goal
The zero-friction drop target (MASTERPLAN §5.1, mcp-hub heritage): agents
capture mid-work without deciding placement/dedup/structure. The curator
(Phase 2) consumes it; Phase 1 ships the drop path + visibility.

## Deliverables
1. `capture` tool per vault: fields `what_it_concerns` (mandatory),
   `why_keep` (mandatory), `content` (mandatory), `source` (optional,
   defaults to client/agent identity + date). Writes a well-formed note into
   `inbox/` per format spec (`status: uncurated`, deterministic capture_id),
   immediately searchable.
2. Duplicate guard: cheap hash dedup against existing inbox entries (exact-
   duplicate drops are acked but not duplicated — response says so).
3. `inbox_status` tool + REST endpoint: count, oldest entry age, last capture.
4. Dashboard v0 hook: explorer (SPEC-110) shows inbox/ prominently with
   uncurated badge.

## Acceptance criteria
- [ ] capture with only mandatory fields yields a format-spec-valid inbox note
      (validated against SPEC-103 parser + conformance rules)
- [ ] missing mandatory field → helpful error naming the field and an example
- [ ] capture_id deterministic and present in frontmatter
- [ ] exact duplicate capture does not create a second file
- [ ] inbox entries rank in normal search with their uncurated status visible

## Non-goals
Curation, promotion ladder mechanics, review/ handling (Phase 2 curator).
