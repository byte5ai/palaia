---
id: SPEC-104
title: Index & hybrid search
phase: 1
depends_on: [SPEC-102, SPEC-103]
model: opus-5
effort: medium
status: draft
---

# SPEC-104: Index & hybrid search

## Goal
The disposable projection: SQLite index over parsed notes with full-text,
vector and hybrid search — rebuildable from files at any time, byte-equivalent
in behavior after rebuild.

## Deliverables
1. `palaia_hub.index` — per-vault SQLite (WAL): entities, observations,
   relations (incl. forward-reference resolution + back-resolution on target
   creation), FTS5 over entities+observations+relations, metadata filters
   (type, tags, dates, custom keys).
2. **Embeddings**: fastembed local default (model per config), chunking with
   fingerprint tracking, sqlite-vec KNN; embedding work runs async off the
   write path (write ack never waits on embeds), with a pending/ready status.
3. **Hybrid search API**: modes `fts | vector | hybrid`, scope/type/date
   filters, sub-note addressability in results (observation/relation hits point
   at their synthetic permalinks).
4. `reindex(vault)` — full rebuild from files; `verify(vault)` — checksum
   consistency report (plugs into SPEC-102 doctor primitives).
5. Consumes SPEC-102 change events for incremental updates.

## Acceptance criteria
- [ ] drop DB → `reindex` → identical results for a fixed query battery
      (golden-vault test)
- [ ] forward reference resolves when target note appears (no full reindex)
- [ ] index lag after a change event < 2s in integration test
- [ ] hybrid beats pure FTS on the SPEC-003 toy-vault relevance battery
      (recall@5 measured, documented in PR)
- [ ] embed backlog visible via status API; queries degrade to FTS cleanly
      while vectors are pending

## Non-goals
Recall/ranking policy and context assembly (SPEC-106); Postgres (never, per
masterplan).

## Model note
Opus 5 / medium — schema and invariants are specified; the judgment lives in
incremental-update correctness and the hybrid merge.
