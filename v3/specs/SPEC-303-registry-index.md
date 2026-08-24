---
id: SPEC-303
title: Registry client + curated add-on index
phase: 3
depends_on: [SPEC-101]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-303: Registry browse + curated index

## Goal
The marketplace's two data sources (MASTERPLAN §5.3): the official MCP
registry (minimally moderated, delegates trust) and palaia's curated index
(the trust layer). This SPEC delivers the data layer + REST; SPEC-304 puts
the UI and install flows on top.

## Deliverables
1. `palaia_hub.registry`: a client for the official registry
   (`registry.modelcontextprotocol.io`, **API v0.1 — frozen**; endpoints and
   quirks in `v3/research/mcp-landscape-2026.md`). Search + detail, cached
   on disk with TTL (the hub must browse fine on a flaky connection and say
   "cached N hours ago"), size- and time-capped fetches, and a clear offline
   state — never a hung dashboard request.
2. Curated palaia index: a **signed JSON document** (format fixed here:
   `{schema_version, generated_at, entries[]}`, each entry
   `{id, name, one_liner, kind: remote|container|mcpb|skill|plugin,
   source (registry ref | image | url), config_schema?, permissions[],
   maintainer, verified: bool}`), fetched from a configurable URL with a
   pinned Ed25519 public key baked into the package (verify with
   `cryptography`; refuse an unsigned/invalid index loudly, fall back to the
   last verified copy on disk). Ship a small starter index as a repo file
   plus the signing script under `v3/tools/` (key NOT in the repo).
3. Manual entries: the third source — a REST-created entry with the same
   shape (`verified: false`, provenance `manual`).
4. One merged read model: `/api/market/search?q=&source=` and
   `/api/market/entry/{id}` return the same entry shape regardless of
   source, with `source` and `verified` always present — the UI never
   special-cases a source.
5. Events: `market.index.updated` (additive; docs/events.md).

## Acceptance criteria
- [ ] registry search/detail against a recorded/mocked v0.1 API; live smoke
      test env-gated on network, skipped honestly otherwise
- [ ] a tampered curated index (bad signature, wrong key, downgraded
      `generated_at`) is refused and the last good copy served, with a
      WARNING naming the reason
- [ ] offline: search returns cached results marked stale; no request hangs
      past its timeout
- [ ] merged search returns all three sources in one shape (contract test)

## Non-goals
Install/lifecycle (SPEC-304); any UI; submission flow for third parties
(Phase 4/5 per masterplan).
