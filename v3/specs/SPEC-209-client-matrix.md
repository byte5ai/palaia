---
id: SPEC-209
title: Client matrix validation
phase: 2
depends_on: [SPEC-203, SPEC-205]
model: sonnet-5
effort: low
status: ready
---

# SPEC-209: Client matrix validation

## Goal
Prove (and document honestly) the MASTERPLAN §6 matrix against a real
Cloud-mode hub — the Phase-2 exit evidence.

## Deliverables
1. Scripted validations where a client is scriptable in this environment
   (Claude Code CLI: full connect+OAuth+tools; scripted MCP clients emulating
   the documented behavior of others).
2. `v3/docs/client-matrix-results.md`: per client — what was verified
   (scripted / manually / not yet), exact steps, quirks found, workarounds.
   Honesty rule: "not verified" is an acceptable cell value; a green cell
   requires evidence.
3. Issues filed (repo issues) for every quirk needing code changes.

## Acceptance criteria
- [ ] Claude Code CLI: end-to-end against Cloud-mode hub with OAuth (real)
- [ ] every §6 row has a filled, evidenced cell
- [ ] connect-page instructions corrected where validation contradicted them
