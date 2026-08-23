---
id: SPEC-210
title: Phase-1 follow-ups — dynamic mounting, embed queue, index status
phase: 2
depends_on: [SPEC-104, SPEC-110, SPEC-111]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-210: Phase-1 follow-ups

## Goal
Close the honest gaps the Phase-1 PRs documented, before they calcify.

## Deliverables
1. **Dynamic gateway mounting**: a vault created via the wizard/API is served
   by MCP without hub restart (rebuild-and-swap the profile mounts safely
   under the running lifespan, or equivalent — document the approach and its
   concurrency story).
2. **Import cold-embed wiring**: SPEC-111's embed queue drains through
   SPEC-104's background worker; progress visible via the status API and the
   dashboard (import UX: "searchable now, semantic search catching up — N%").
3. **Index status surface**: REST + dashboard tile for IndexStatus (backlog,
   lag, last reindex); `doctor` includes index verify.
4. Small documented leftovers from the PR bodies: vector filters post-KNN
   noted as known limitation in docs; wizard steps 1–2 persistence (admin
   account + mode now exist via SPEC-203/205 — wire the wizard to them).

## Acceptance criteria
- [ ] e2e: create vault via API → MCP tool call on it succeeds WITHOUT restart
- [ ] import of a 50-note fixture: FTS-searchable immediately, embeds drain in
      background, progress endpoint reflects it, done-event on the bus
- [ ] index status visible in dashboard (screenshot in PR)
- [ ] wizard persists admin + mode via the new APIs (when SPEC-203/205 merged;
      else keep the seam and tick honestly)
