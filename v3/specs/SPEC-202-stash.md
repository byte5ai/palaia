---
id: SPEC-202
title: Stash — cross-session cache tool family
phase: 2
depends_on: [SPEC-105, SPEC-108]
model: sonnet-5
effort: low
status: ready
---

# SPEC-202: Stash

## Goal
The P5 pillar: structured cross-session cache, deliberately SEPARATE from
memory (the three-stores lesson: cache ≠ operating memory ≠ knowledge).

## Deliverables
1. Hub-level SQLite store: namespaced keys, JSON values, per-entry TTL with
   stale-then-hard-expiry, per-entry size limit + total budget with LRU
   eviction, created/updated/accessed metadata.
2. Gateway tool family `stash_set/get/del/list/status` mounted like a vault
   family (own IDENTITY line: "cache for data, NOT memory — knowledge belongs
   in memory tools"), behavior annotations, dual output, alias absorption.
3. Scopes `stash:read`/`stash:write` enforced per-tool (SPEC-108 pattern);
   REST mirror under `/api/stash` for jobs/dashboard.
4. Emits `stash.*` events on the SPEC-201 bus (if merged; else the internal
   bus stub).

## Acceptance criteria
- [ ] TTL expiry and stale marker behave per config (clock-injectable tests)
- [ ] budget eviction evicts LRU first, never the entry being written
- [ ] read-scoped token cannot write (per-tool scope test)
- [ ] tool descriptions distinguish stash from memory (IDENTITY lint test)
- [ ] golden tools snapshot regenerated via the documented command

## Non-goals
Cross-host replication; binary blobs (JSON/text only in v1).
